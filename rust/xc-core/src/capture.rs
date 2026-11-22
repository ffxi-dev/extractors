//! Reads a xicap capture through xicap's C API (bindings/go/capi.h): its header, then its packets in order.

use std::ffi::{CStr, CString, c_char, c_void};
use std::path::Path;

use crate::packet::Packet;

#[repr(C)]
struct Meta {
    capture_id: [u8; 16],
    previous_capture_id: [u8; 16],
    start_timestamp: u64,
    origin: u8,
    server_kind: u8,
    capture_agent: *const c_char,
    client_version: *const c_char,
    content_id: u32,
    character_id: u32,
    character_name: *const c_char,
    world_name: *const c_char,
    has_source: bool,
    source_format: *const c_char,
    source_format_version: *const c_char,
    skipped_records: u32,
    source_metadata: *const u8,
    source_metadata_size: usize,
}

#[repr(C)]
struct RawInfo {
    metadata: Meta,
    complete: bool,
    end_timestamp: u64,
    packet_count: u64,
}

#[repr(C)]
struct RawPacket {
    timestamp: u64,
    flags: u16,
    channel: u8,
    opcode: u16,
    data: *const u8,
    size: usize,
    markers: *const c_void,
    marker_count: usize,
}

enum RawReader {}

unsafe extern "C" {
    fn xicap_reader_open(path: *const c_char, out: *mut *mut RawReader, info: *mut RawInfo) -> *mut c_char;
    fn xicap_reader_next(r: *mut RawReader, out: *mut RawPacket, more: *mut bool) -> *mut c_char;
    fn xicap_reader_close(r: *mut RawReader);
    fn free(p: *mut c_void);
}

/// xicap's packet flag for a packet from the client.
pub const CLIENT_TO_SERVER: u16 = 0x0001;
/// xicap's server kinds.
pub const SERVER_UNKNOWN: u8 = 0;
pub const SERVER_RETAIL: u8 = 1;
pub const SERVER_PRIVATE: u8 = 2;

/// The capture's header and trailer.
#[derive(Clone, Debug, Default)]
pub struct Info {
    pub client_version: String,
    pub character: String,
    pub character_id: u32,
    pub start_ms: u64,
    /// 0 for a cut-off capture, which has no trailer.
    pub end_ms: u64,
    /// The trailer's count; 0 without one.
    pub packets: u64,
    pub server_kind: u8,
    pub complete: bool,
}

pub struct Reader {
    r: *mut RawReader,
    pub info: Info,
    raw: RawPacket,
    idx: u64,
}

fn error(e: *mut c_char) -> Result<(), String> {
    if e.is_null() {
        return Ok(());
    }
    let msg = unsafe { CStr::from_ptr(e) }.to_string_lossy().into_owned();
    unsafe { free(e.cast()) };
    Err(msg)
}

fn text(p: *const c_char) -> String {
    if p.is_null() {
        return String::new();
    }
    unsafe { CStr::from_ptr(p) }.to_string_lossy().into_owned()
}

impl Reader {
    pub fn open(path: &Path) -> Result<Reader, String> {
        let c = CString::new(path.to_str().ok_or("path is not UTF-8")?).map_err(|e| e.to_string())?;
        let mut r = std::ptr::null_mut();
        let mut info: RawInfo = unsafe { std::mem::zeroed() };
        error(unsafe { xicap_reader_open(c.as_ptr(), &mut r, &mut info) })?;
        let m = &info.metadata;
        let info = Info {
            client_version: text(m.client_version),
            character: text(m.character_name),
            character_id: m.character_id,
            start_ms: m.start_timestamp,
            end_ms: info.end_timestamp,
            packets: info.packet_count,
            server_kind: m.server_kind,
            complete: info.complete,
        };
        Ok(Reader { r, info, raw: unsafe { std::mem::zeroed() }, idx: 0 })
    }

    /// The next packet, or None at the end. It borrows the reader until the next call.
    #[allow(clippy::should_implement_trait)] // a lending iterator: Iterator cannot lend
    pub fn next(&mut self) -> Result<Option<Packet<'_>>, String> {
        let mut more = false;
        error(unsafe { xicap_reader_next(self.r, &mut self.raw, &mut more) })?;
        if !more {
            return Ok(None);
        }
        let p = &self.raw;
        let data = if p.size == 0 { &[][..] } else { unsafe { std::slice::from_raw_parts(p.data, p.size) } };
        let idx = self.idx;
        self.idx += 1;
        Ok(Some(Packet {
            idx,
            ts_ms: p.timestamp as i64,
            channel: p.channel,
            direction: (p.flags & CLIENT_TO_SERVER) as u8,
            opcode: p.opcode,
            flags: p.flags,
            data,
        }))
    }
}

impl Drop for Reader {
    fn drop(&mut self) {
        unsafe { xicap_reader_close(self.r) }
    }
}
