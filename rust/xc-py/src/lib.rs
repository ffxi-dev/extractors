//! extractors_rs: one pass over a capture with the Rust extractors, their rows as pyarrow tables typed as
//! Python's Sink makes them (COMMON's columns, then the table's). ffxi_extractors.index.run calls it.

use std::path::Path;

use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList};
use xc_core::extract::{COMMON, Col, Rows};
use xc_core::run::{Error, See, walk};
use xc_core::stats::CaptureStats;
use xc_core::{Extractor, Ty};

fn pa_type<'py>(pa: &Bound<'py, PyModule>, ty: Ty) -> PyResult<Bound<'py, PyAny>> {
    let simple = |name: &str| pa.call_method0(name);
    Ok(match ty {
        Ty::Bool => simple("bool_")?,
        Ty::I32 => simple("int32")?,
        Ty::I64 => simple("int64")?,
        Ty::F32 => simple("float32")?,
        Ty::F64 => simple("float64")?,
        Ty::Str => simple("string")?,
        Ty::ListI32 => pa.call_method1("list_", (simple("int32")?,))?,
        Ty::ListI64 => pa.call_method1("list_", (simple("int64")?,))?,
        Ty::ListStr => pa.call_method1("list_", (simple("string")?,))?,
    })
}

/// Arrow's validity bitmap, or None when every value is there.
fn validity<T>(xs: &[Option<T>]) -> Option<Vec<u8>> {
    if xs.iter().all(Option::is_some) {
        return None;
    }
    let mut bits = vec![0u8; xs.len().div_ceil(8)];
    for (i, x) in xs.iter().enumerate() {
        if x.is_some() {
            bits[i / 8] |= 1 << (i % 8);
        }
    }
    Some(bits)
}

fn bitmap(xs: impl ExactSizeIterator<Item = bool>) -> Vec<u8> {
    let mut bits = vec![0u8; xs.len().div_ceil(8)];
    for (i, x) in xs.enumerate() {
        if x {
            bits[i / 8] |= 1 << (i % 8);
        }
    }
    bits
}

struct Arrow<'py> {
    py: Python<'py>,
    pa: Bound<'py, PyModule>,
}

impl<'py> Arrow<'py> {
    fn buffer(&self, b: Option<Vec<u8>>) -> PyResult<Bound<'py, PyAny>> {
        match b {
            Some(b) => self.pa.call_method1("py_buffer", (PyBytes::new(self.py, &b),)),
            None => Ok(self.py.None().into_bound(self.py)),
        }
    }

    fn array(
        &self,
        ty: Ty,
        len: usize,
        buffers: Vec<Option<Vec<u8>>>,
        child: Option<Bound<'py, PyAny>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let bufs = PyList::new(self.py, buffers.into_iter().map(|b| self.buffer(b)).collect::<PyResult<Vec<_>>>()?)?;
        let kw = PyDict::new(self.py);
        if let Some(c) = child {
            kw.set_item("children", PyList::new(self.py, [c])?)?;
        }
        self.pa.getattr("Array")?.call_method("from_buffers", (pa_type(&self.pa, ty)?, len, bufs), Some(&kw))
    }

    fn values<T: Copy + Default, const N: usize>(
        &self,
        ty: Ty,
        xs: &[Option<T>],
        le: fn(T) -> [u8; N],
    ) -> PyResult<Bound<'py, PyAny>> {
        let data: Vec<u8> = xs.iter().flat_map(|x| le(x.unwrap_or_default())).collect();
        self.array(ty, xs.len(), vec![validity(xs), Some(data)], None)
    }

    fn strings(&self, xs: &[Option<String>]) -> PyResult<Bound<'py, PyAny>> {
        let mut offsets = Vec::with_capacity(4 * (xs.len() + 1));
        let mut data = Vec::new();
        offsets.extend(0i32.to_le_bytes());
        for x in xs {
            data.extend(x.as_deref().unwrap_or("").as_bytes());
            offsets.extend(i32::try_from(data.len()).expect("a string column over 2 GB").to_le_bytes());
        }
        self.array(Ty::Str, xs.len(), vec![validity(xs), Some(offsets), Some(data)], None)
    }

    fn list<T>(
        &self,
        ty: Ty,
        xs: &[Option<Vec<T>>],
        child: impl Fn(Vec<&T>) -> PyResult<Bound<'py, PyAny>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let mut offsets = Vec::with_capacity(4 * (xs.len() + 1));
        let mut items = Vec::new();
        offsets.extend(0i32.to_le_bytes());
        for x in xs {
            items.extend(x.iter().flatten());
            offsets.extend((items.len() as i32).to_le_bytes());
        }
        let child = child(items)?;
        self.array(ty, xs.len(), vec![validity(xs), Some(offsets)], Some(child))
    }

    fn column(&self, c: &Col) -> PyResult<Bound<'py, PyAny>> {
        match c {
            Col::Bool(xs) => {
                let data = bitmap(xs.iter().map(|x| x.unwrap_or(false)));
                self.array(Ty::Bool, xs.len(), vec![validity(xs), Some(data)], None)
            }
            Col::I32(xs) => self.values(Ty::I32, xs, i32::to_le_bytes),
            Col::I64(xs) => self.values(Ty::I64, xs, i64::to_le_bytes),
            Col::F32(xs) => self.values(Ty::F32, xs, f32::to_le_bytes),
            Col::F64(xs) => self.values(Ty::F64, xs, f64::to_le_bytes),
            Col::Str(xs) => self.strings(xs),
            Col::ListI32(xs) => self.list(Ty::ListI32, xs, |v| {
                self.values(Ty::I32, &v.into_iter().copied().collect::<Vec<_>>(), i32::to_le_bytes)
            }),
            Col::ListI64(xs) => self.list(Ty::ListI64, xs, |v| {
                self.values(Ty::I64, &v.into_iter().copied().collect::<Vec<_>>(), i64::to_le_bytes)
            }),
            Col::ListStr(xs) => {
                self.list(Ty::ListStr, xs, |v| self.strings(&v.into_iter().cloned().collect::<Vec<_>>()))
            }
        }
    }

    fn table(&self, cols: Vec<(&str, Bound<'py, PyAny>)>) -> PyResult<Bound<'py, PyAny>> {
        let d = PyDict::new(self.py);
        for (name, c) in cols {
            d.set_item(name, c)?;
        }
        self.pa.call_method1("table", (d,))
    }

    /// An extractor table's rows, COMMON's columns first.
    fn rows(&self, rows: &Rows, capture_id: &str, client_version: &str) -> PyResult<Bound<'py, PyAny>> {
        let n = rows.len();
        let repeat = |s: &str| {
            self.pa.call_method1("repeat", (self.pa.call_method1("scalar", (s, pa_type(&self.pa, Ty::Str)?))?, n))
        };
        let mut cols = vec![
            (COMMON[0].0, repeat(capture_id)?),
            (COMMON[1].0, self.column(&Col::I64(rows.idx.clone()))?),
            (COMMON[2].0, self.column(&Col::I64(rows.ts_ms.clone()))?),
            (COMMON[3].0, repeat(client_version)?),
        ];
        for (&(name, _), c) in rows.table.columns.iter().zip(&rows.cols) {
            cols.push((name, self.column(c)?));
        }
        self.table(cols)
    }
}

/// One pass over the capture for these units: extractor names, "decode" (its tables with no Mogsafe record
/// and no release), and "world" (the walk alone, no tables). Returns each table's rows by table name.
#[pyfunction]
fn run<'py>(py: Python<'py>, path: &str, capture_id: &str, units: Vec<String>) -> PyResult<Bound<'py, PyDict>> {
    let mut xs: Vec<Box<dyn Extractor>> = Vec::new();
    let mut stats = None;
    for u in &units {
        match u.as_str() {
            "world" => {}
            "decode" => stats = Some(CaptureStats::default()),
            name => xs
                .push(xc_all::by_name(name).ok_or_else(|| PyValueError::new_err(format!("no Rust extractor {name}")))?),
        }
    }
    let see = stats.as_mut().map(|s| s as &mut dyn See);
    let (info, world, outs) = walk(Path::new(path), &mut xs, see).map_err(|e| match e {
        Error::TooLarge => py
            .import("ffxi_extractors.capture")
            .and_then(|m| m.getattr("Skipped"))
            .map_or_else(|err| err, |skipped| PyErr::from_value(skipped.call1((e.to_string(),)).unwrap())),
        Error::Read(e) => PyRuntimeError::new_err(e),
    })?;
    let arrow = Arrow { py, pa: py.import("pyarrow")? };
    let out = PyDict::new(py);
    for o in &outs {
        for rows in &o.tables {
            out.set_item(rows.table.name, arrow.rows(rows, capture_id, &info.client_version)?)?;
        }
    }
    if let Some(s) = &stats {
        let character_id = Some(info.character_id as i64).filter(|&c| c != 0).or(world.character_id);
        for (name, cols) in s.tables(capture_id, &info, character_id) {
            let cols = cols.iter().map(|(c, col)| Ok((*c, arrow.column(col)?))).collect::<PyResult<Vec<_>>>()?;
            out.set_item(name, arrow.table(cols)?)?;
        }
    }
    Ok(out)
}

/// Each Rust extractor's name, version, reads, sparse, and tables: [(name, [(column, type)])], for the Python side
/// to check against its own declarations.
#[pyfunction]
fn extractors<'py>(py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
    let pa = py.import("pyarrow")?;
    let mut out = Vec::new();
    for x in xc_all::all() {
        let m = x.meta();
        let d = PyDict::new(py);
        d.set_item("name", m.name)?;
        d.set_item("version", m.version)?;
        d.set_item("reads", m.reads.to_vec())?;
        d.set_item("sparse", m.sparse)?;
        let mut tables = Vec::new();
        for t in m.tables {
            let cols = t.columns.iter().map(|&(c, ty)| Ok((c, pa_type(&pa, ty)?))).collect::<PyResult<Vec<_>>>()?;
            tables.push((t.name, cols));
        }
        d.set_item("tables", tables)?;
        out.push(d);
    }
    PyList::new(py, out)
}

#[pymodule]
fn extractors_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(run, m)?)?;
    m.add_function(wrap_pyfunction!(extractors, m)?)?;
    Ok(())
}
