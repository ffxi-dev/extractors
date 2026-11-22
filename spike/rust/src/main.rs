// Spike: read a xicap capture through xicap's C API, decode every s2c 0x028 bitstream as
// ffxi_packets' _action does, and print one row per target result (or a count with --count).
use std::ffi::{c_char, CStr, CString};
use std::io::{BufWriter, Write};

#[repr(C)] struct Meta { capture_id: [u8; 16], prev: [u8; 16], start: u64, origin: u8, server_kind: u8,
    agent: *const c_char, client_version: *const c_char, content_id: u32, character_id: u32,
    character_name: *const c_char, world_name: *const c_char, has_source: bool, source_format: *const c_char,
    source_format_version: *const c_char, skipped: u32, source_metadata: *const u8, source_metadata_size: usize }
#[repr(C)] struct Info { meta: Meta, complete: bool, end: u64, count: u64 }
#[repr(C)] struct Pkt { ts: u64, flags: u16, channel: u8, opcode: u16, data: *const u8, size: usize,
    markers: *const u8, marker_count: usize }
enum Reader {}
extern "C" {
    fn xicap_reader_open(path: *const c_char, out: *mut *mut Reader, info: *mut Info) -> *mut c_char;
    fn xicap_reader_next(r: *mut Reader, out: *mut Pkt, more: *mut bool) -> *mut c_char;
    fn xicap_reader_close(r: *mut Reader);
}

struct Bits<'a> { raw: &'a [u8], pos: usize }
impl Bits<'_> {
    // LSB-first; bits past the end read as zero, as _Reader.
    fn read(&mut self, n: usize) -> u64 {
        let (start, shift) = (self.pos >> 3, self.pos & 7);
        let mut w = [0u8; 8];
        let end = (start + 8).min(self.raw.len());
        if start < end { w[..end - start].copy_from_slice(&self.raw[start..end]); }
        self.pos += n;
        (u64::from_le_bytes(w) >> shift) & ((1u64 << n) - 1) // n <= 32, so shift + n <= 39 bits fit
    }
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let count_only = args.iter().any(|a| a == "--count");
    let path = CString::new(args[1].clone()).unwrap();
    let mut r: *mut Reader = std::ptr::null_mut();
    let mut info: Info = unsafe { std::mem::zeroed() };
    let err = unsafe { xicap_reader_open(path.as_ptr(), &mut r, &mut info) };
    if !err.is_null() { panic!("{}", unsafe { CStr::from_ptr(err) }.to_string_lossy()); }
    let out = std::io::stdout();
    let mut w = BufWriter::with_capacity(1 << 20, out.lock());
    let (mut idx, mut rows, mut actions, mut zone) = (0u64, 0u64, 0u64, 0u64);
    let mut names: std::collections::HashMap<u32, u32> = Default::default(); // act index -> unique no (world stand-in)
    let mut p: Pkt = unsafe { std::mem::zeroed() };
    let mut more = true;
    loop {
        let e = unsafe { xicap_reader_next(r, &mut p, &mut more) };
        if !e.is_null() { panic!("{}", unsafe { CStr::from_ptr(e) }.to_string_lossy()); }
        if !more { break; }
        let i = idx; idx += 1;
        if p.channel != 0 || p.flags & 1 != 0 { continue; }
        let raw = unsafe { std::slice::from_raw_parts(p.data, p.size) };
        match p.opcode {
            0x00A if raw.len() > 0x34 => zone = u16::from_le_bytes([raw[0x30], raw[0x31]]) as u64,
            0x00E if raw.len() > 10 => { names.insert(u16::from_le_bytes([raw[8], raw[9]]) as u32, u32::from_le_bytes([raw[4], raw[5], raw[6], raw[7]])); }
            0x028 if raw.len() >= 5 && raw[0] == 0x28 => {
                actions += 1;
                let mut b = Bits { raw, pos: 40 };
                let actor = b.read(32); let tc = b.read(6); b.read(4); let cmd = b.read(4); let arg = b.read(32); let ainfo = b.read(32);
                for t in 0..tc {
                    let target = b.read(32); let rc = b.read(4);
                    for ri in 0..rc {
                        let v: Vec<u64> = [3, 2, 12, 5, 5, 17, 10, 31].iter().map(|&n| b.read(n)).collect();
                        let proc = if b.read(1) == 1 { Some([b.read(6), b.read(4), b.read(17), b.read(10)]) } else { None };
                        let react = if b.read(1) == 1 { Some([b.read(6), b.read(4), b.read(14), b.read(10)]) } else { None };
                        rows += 1;
                        if !count_only {
                            let ex = |x: Option<[u64; 4]>| x.map_or("N\tN\tN\tN".to_string(), |a| format!("{}\t{}\t{}\t{}", a[0], a[1], a[2], a[3]));
                            writeln!(w, "{i}\t{actor}\t{cmd}\t{arg}\t{ainfo}\t{target}\t{t}\t{ri}\t{}\t{}\t{}",
                                v.iter().map(|x| x.to_string()).collect::<Vec<_>>().join("\t"), ex(proc), ex(react)).unwrap();
                        }
                    }
                }
            }
            _ => {}
        }
    }
    unsafe { xicap_reader_close(r) };
    eprintln!("packets {idx} actions {actions} result_rows {rows} zone {zone} entities {}", names.len());
}
