//! Reject private clipboard transactions before history persistence.
//! Check the sequence before reading and after all high-level reads, before IO.
pub const PRIVATE_FORMAT: &str = "VersePic.PrivateCapture.v1";
pub const EXCLUDE_FORMAT: &str = "ExcludeClipboardContentFromMonitorProcessing";

fn permits_snapshot(before: Option<u32>, after: Option<u32>) -> bool {
    matches!((before, after), (Some(a), Some(b)) if a != 0 && a == b)
}

#[cfg(target_os = "windows")]
pub fn public_sequence() -> Option<u32> {
    use std::ffi::c_void;
    #[link(name = "user32")]
    extern "system" {
        fn OpenClipboard(window: *mut c_void) -> i32;
        fn CloseClipboard() -> i32;
        fn RegisterClipboardFormatW(name: *const u16) -> u32;
        fn IsClipboardFormatAvailable(format: u32) -> i32;
        fn GetClipboardSequenceNumber() -> u32;
    }
    unsafe {
        if OpenClipboard(std::ptr::null_mut()) == 0 {
            return None; // Busy/unreadable is never permission to persist data.
        }
        struct Close;
        impl Drop for Close {
            fn drop(&mut self) { unsafe { CloseClipboard(); } }
        }
        let _close = Close;
        for name in [PRIVATE_FORMAT, EXCLUDE_FORMAT] {
            let wide: Vec<u16> = name.encode_utf16().chain(std::iter::once(0)).collect();
            let format = RegisterClipboardFormatW(wide.as_ptr());
            if format == 0 || IsClipboardFormatAvailable(format) != 0 {
                return None;
            }
        }
        let sequence = GetClipboardSequenceNumber();
        if sequence == 0 { None } else { Some(sequence) }
    }
}

#[cfg(not(target_os = "windows"))]
pub fn public_sequence() -> Option<u32> { Some(1) }

pub fn unchanged_public_snapshot(sequence: Option<u32>) -> bool {
    permits_snapshot(sequence, public_sequence())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn only_same_nonzero_public_sequence_can_be_persisted() {
        assert!(permits_snapshot(Some(18), Some(18)));
        assert!(!permits_snapshot(Some(18), Some(19)));
        assert!(!permits_snapshot(Some(18), None));
        assert!(!permits_snapshot(None, Some(19)));
        assert!(!permits_snapshot(None, None));
        assert!(!permits_snapshot(Some(0), Some(0)));
    }
}
