//! extract.py's contract: an extractor reads one capture's packets in order, with the world so far, and
//! writes rows to its own tables. Its name, version, reads, and tables match its Python declaration, which
//! keeps the docs and the ClickHouse schema; xc-py checks the two agree.

use crate::packet::{Decoded, Packet};
use crate::world::World;

/// A column's type, as its Python Column's pyarrow type.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Ty {
    Bool,
    I32,
    I64,
    F32,
    F64,
    Str,
    ListI32,
    ListI64,
    ListStr,
}

#[derive(Debug)]
pub struct Table {
    pub name: &'static str,
    /// Its own columns, in the Python Table's order; every row also carries COMMON's first.
    pub columns: &'static [(&'static str, Ty)],
}

/// The columns every extractor row carries before its own.
pub const COMMON: [(&str, Ty); 4] =
    [("capture_id", Ty::Str), ("idx", Ty::I64), ("ts_ms", Ty::I64), ("client_version", Ty::Str)];

#[derive(Debug)]
pub struct Meta {
    pub name: &'static str,
    pub version: u32,
    /// (direction, opcode): 0 is to the client, 1 from it.
    pub reads: &'static [(u8, u16)],
    pub tables: &'static [Table],
}

pub trait Extractor {
    fn meta(&self) -> &'static Meta;

    /// A packet of one of meta().reads, after the world has read it.
    fn packet(&mut self, p: &Packet, f: &Decoded, world: &World, out: &mut Out);

    /// After the last packet.
    fn finish(&mut self, _world: &World, _out: &mut Out) {}
}

/// A value for a column. From covers the Rust types, Option of them as None.
#[derive(Clone, Debug, PartialEq)]
pub enum V {
    Null,
    Int(i64),
    Float(f64),
    Bool(bool),
    Str(String),
    Ints(Vec<Option<i64>>),
    Strs(Vec<Option<String>>),
}

macro_rules! from {
    ($($t:ty => $v:ident as $c:ty),*) => {$(
        impl From<$t> for V {
            fn from(x: $t) -> V {
                V::$v(x as $c)
            }
        }
    )*};
}
from!(i64 => Int as i64, i32 => Int as i64, i16 => Int as i64, i8 => Int as i64, u32 => Int as i64,
      u16 => Int as i64, u8 => Int as i64, usize => Int as i64, f64 => Float as f64, f32 => Float as f64);

impl From<bool> for V {
    fn from(x: bool) -> V {
        V::Bool(x)
    }
}
impl From<String> for V {
    fn from(x: String) -> V {
        V::Str(x)
    }
}
impl From<&str> for V {
    fn from(x: &str) -> V {
        V::Str(x.to_string())
    }
}
impl From<Vec<Option<i64>>> for V {
    fn from(x: Vec<Option<i64>>) -> V {
        V::Ints(x)
    }
}
impl From<Vec<Option<String>>> for V {
    fn from(x: Vec<Option<String>>) -> V {
        V::Strs(x)
    }
}
impl<T: Into<V>> From<Option<T>> for V {
    fn from(x: Option<T>) -> V {
        x.map_or(V::Null, Into::into)
    }
}

/// A row's values by column name, as Python's emit(table, p, **values): `row! { actor_id: a, resend: r }`.
#[macro_export]
macro_rules! row {
    ($($k:ident: $v:expr),* $(,)?) => {
        [$((stringify!($k), $crate::extract::V::from($v))),*]
    };
}

/// One column's values, None where a row has none.
#[derive(Clone, Debug)]
pub enum Col {
    Bool(Vec<Option<bool>>),
    I32(Vec<Option<i32>>),
    I64(Vec<Option<i64>>),
    F32(Vec<Option<f32>>),
    F64(Vec<Option<f64>>),
    Str(Vec<Option<String>>),
    ListI32(Vec<Option<Vec<Option<i32>>>>),
    ListI64(Vec<Option<Vec<Option<i64>>>>),
    ListStr(Vec<Option<Vec<Option<String>>>>),
}

fn i32_of(name: &str, v: i64) -> i32 {
    i32::try_from(v).unwrap_or_else(|_| panic!("{name}: {v} does not fit an int32"))
}

impl Col {
    fn new(ty: Ty) -> Col {
        match ty {
            Ty::Bool => Col::Bool(Vec::new()),
            Ty::I32 => Col::I32(Vec::new()),
            Ty::I64 => Col::I64(Vec::new()),
            Ty::F32 => Col::F32(Vec::new()),
            Ty::F64 => Col::F64(Vec::new()),
            Ty::Str => Col::Str(Vec::new()),
            Ty::ListI32 => Col::ListI32(Vec::new()),
            Ty::ListI64 => Col::ListI64(Vec::new()),
            Ty::ListStr => Col::ListStr(Vec::new()),
        }
    }

    pub fn len(&self) -> usize {
        match self {
            Col::Bool(c) => c.len(),
            Col::I32(c) => c.len(),
            Col::I64(c) => c.len(),
            Col::F32(c) => c.len(),
            Col::F64(c) => c.len(),
            Col::Str(c) => c.len(),
            Col::ListI32(c) => c.len(),
            Col::ListI64(c) => c.len(),
            Col::ListStr(c) => c.len(),
        }
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    fn push(&mut self) {
        match self {
            Col::Bool(c) => c.push(None),
            Col::I32(c) => c.push(None),
            Col::I64(c) => c.push(None),
            Col::F32(c) => c.push(None),
            Col::F64(c) => c.push(None),
            Col::Str(c) => c.push(None),
            Col::ListI32(c) => c.push(None),
            Col::ListI64(c) => c.push(None),
            Col::ListStr(c) => c.push(None),
        }
    }

    /// Set row i, typed as pyarrow would take the Python value: an int fits an int32 or reads as a float.
    fn set(&mut self, name: &str, i: usize, v: V) {
        match (self, v) {
            (Col::Bool(c), V::Null) => c[i] = None,
            (Col::I32(c), V::Null) => c[i] = None,
            (Col::I64(c), V::Null) => c[i] = None,
            (Col::F32(c), V::Null) => c[i] = None,
            (Col::F64(c), V::Null) => c[i] = None,
            (Col::Str(c), V::Null) => c[i] = None,
            (Col::ListI32(c), V::Null) => c[i] = None,
            (Col::ListI64(c), V::Null) => c[i] = None,
            (Col::ListStr(c), V::Null) => c[i] = None,
            (Col::Bool(c), V::Bool(b)) => c[i] = Some(b),
            (Col::I32(c), V::Int(x)) => c[i] = Some(i32_of(name, x)),
            (Col::I64(c), V::Int(x)) => c[i] = Some(x),
            (Col::F32(c), V::Int(x)) => c[i] = Some(x as f32),
            (Col::F32(c), V::Float(x)) => c[i] = Some(x as f32),
            (Col::F64(c), V::Int(x)) => c[i] = Some(x as f64),
            (Col::F64(c), V::Float(x)) => c[i] = Some(x),
            (Col::Str(c), V::Str(s)) => c[i] = Some(s),
            (Col::ListI32(c), V::Ints(xs)) => c[i] = Some(xs.into_iter().map(|x| x.map(|x| i32_of(name, x))).collect()),
            (Col::ListI64(c), V::Ints(xs)) => c[i] = Some(xs),
            (Col::ListStr(c), V::Strs(xs)) => c[i] = Some(xs),
            (c, v) => panic!("{name}: {v:?} is not a value of {c:?}"),
        }
    }

    fn get(&self, i: usize) -> V {
        match self {
            Col::Bool(c) => c[i].into(),
            Col::I32(c) => c[i].into(),
            Col::I64(c) => c[i].into(),
            Col::F32(c) => c[i].into(),
            Col::F64(c) => c[i].into(),
            Col::Str(c) => c[i].clone().into(),
            Col::ListI32(c) => c[i].as_ref().map(|xs| xs.iter().map(|x| x.map(i64::from)).collect::<Vec<_>>()).into(),
            Col::ListI64(c) => c[i].clone().into(),
            Col::ListStr(c) => c[i].clone().into(),
        }
    }
}

/// One table's rows so far, a column at a time, in the order they were emitted.
#[derive(Debug)]
pub struct Rows {
    pub table: &'static Table,
    pub idx: Vec<Option<i64>>,
    pub ts_ms: Vec<Option<i64>>,
    /// One per table.columns.
    pub cols: Vec<Col>,
}

impl Rows {
    fn new(table: &'static Table) -> Rows {
        Rows {
            table,
            idx: Vec::new(),
            ts_ms: Vec::new(),
            cols: table.columns.iter().map(|&(_, t)| Col::new(t)).collect(),
        }
    }

    pub fn len(&self) -> usize {
        self.idx.len()
    }

    pub fn is_empty(&self) -> bool {
        self.idx.is_empty()
    }

    fn column(&self, name: &str) -> usize {
        self.table
            .columns
            .iter()
            .position(|&(c, _)| c == name)
            .unwrap_or_else(|| panic!("{} has no column {name}", self.table.name))
    }

    /// Row i's value of a column, idx and ts_ms included.
    pub fn get(&self, i: usize, name: &str) -> V {
        match name {
            "idx" => self.idx[i].into(),
            "ts_ms" => self.ts_ms[i].into(),
            _ => self.cols[self.column(name)].get(i),
        }
    }
}

/// A row emitted, to fill in later: Python's emit returns the row an extractor may change until the end.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct RowId {
    table: usize,
    row: usize,
}

/// One extractor's rows for one capture, by table: what Python's Sink collects.
#[derive(Debug)]
pub struct Out {
    pub tables: Vec<Rows>,
}

impl Out {
    pub fn new(meta: &'static Meta) -> Out {
        Out { tables: meta.tables.iter().map(Rows::new).collect() }
    }

    fn table(&self, name: &str) -> usize {
        self.tables.iter().position(|t| t.table.name == name).unwrap_or_else(|| panic!("no table {name}"))
    }

    /// Add a row with these values; columns left out have none. idx and ts_ms are p's, None without one.
    pub fn emit<const N: usize>(&mut self, table: &str, p: Option<&Packet>, values: [(&str, V); N]) -> RowId {
        let t = self.table(table);
        let rows = &mut self.tables[t];
        let i = rows.len();
        rows.idx.push(p.map(|p| p.idx as i64));
        rows.ts_ms.push(p.map(|p| p.ts_ms));
        for c in &mut rows.cols {
            c.push();
        }
        let id = RowId { table: t, row: i };
        for (name, v) in values {
            self.set(id, name, v);
        }
        id
    }

    /// Change a row emitted before.
    pub fn set(&mut self, id: RowId, name: &str, v: impl Into<V>) {
        let rows = &mut self.tables[id.table];
        let c = rows.column(name);
        rows.cols[c].set(name, id.row, v.into());
    }

    pub fn get(&self, id: RowId, name: &str) -> V {
        self.tables[id.table].get(id.row, name)
    }

    /// A table's rows.
    pub fn rows(&self, table: &str) -> &Rows {
        &self.tables[self.table(table)]
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    static T: [Table; 1] =
        [Table { name: "t", columns: &[("a", Ty::I32), ("b", Ty::F32), ("c", Ty::Str), ("d", Ty::ListI32)] }];
    static M: Meta = Meta { name: "x", version: 1, reads: &[], tables: &T };

    #[test]
    fn rows_are_typed_and_held() {
        let mut out = Out::new(&M);
        let id = out.emit("t", None, row! { a: 1, b: 0.1f64, d: vec![Some(1), None] });
        out.emit("t", None, row! { c: "x" });
        out.set(id, "c", Some("later"));
        let r = out.rows("t");
        assert_eq!(r.len(), 2);
        assert_eq!(r.get(0, "a"), V::Int(1));
        assert_eq!(r.get(0, "b"), V::Float(0.1f32 as f64));
        assert_eq!(r.get(0, "c"), V::Str("later".into()));
        assert_eq!(r.get(0, "d"), V::Ints(vec![Some(1), None]));
        assert_eq!((r.get(1, "a"), r.get(1, "idx")), (V::Null, V::Null));
    }

    #[test]
    #[should_panic(expected = "does not fit an int32")]
    fn int32_overflows() {
        Out::new(&M).emit("t", None, row! { a: 1i64 << 40 });
    }

    #[test]
    #[should_panic(expected = "t has no column e")]
    fn unknown_column() {
        Out::new(&M).emit("t", None, row! { e: 1 });
    }
}
