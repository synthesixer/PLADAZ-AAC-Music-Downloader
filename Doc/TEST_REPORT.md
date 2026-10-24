# PLADAZ — Test Report & Verification Matrix (Phase 5)

> **รายงานผลการทดสอบและความครอบคลุมข้อกำหนด (Test Report & Traceability Matrix)**
>
> **ภาษา:** ไทย  
> **ชื่อโครงการ:** PLADAZ  
> **เวอร์ชันโครงการ:** v1.0.0 (`pladaz.__version__`)  
> **อ้างอิง:** `IMPLEMENT_PLAN.md` v2.5, `SYSTEM_DESIGN.md` v2.3, `PROJECT_PROGRESS.md` (2026-10-24)  
> **วันที่จัดทำ:** 2026-10-24  
> **ผู้จัดทำ:** Senior QA / Release Engineer

---

## 1. สภาพแวดล้อมระบบที่ใช้ทดสอบ (Test Environment)

บันทึกจากค่าจริงของเครื่องทดสอบ (ตรวจวัด ณ วันที่ 2026-10-24):

| รายการ | รายละเอียด / เวอร์ชันจริง | หมายเหตุ |
|---|---|---|
| **ระบบปฏิบัติการ (OS)** | Windows 11 Build 10.0.26200-SP0 (64-bit AMD64) | เครื่องสำหรับพัฒนาและทดสอบอัตโนมัติ |
| **Python** | 3.13.5 (tags/v3.13.5:6cb20a2, MSC v.1943 64 bit) | รันใน Virtual Environment (`.\venv`) |
| **pywebview** | 6.2.1 | Framework สำหรับ App Shell และ Native JS Bridge |
| **PyInstaller** | 6.22.3 | ใช้แพ็กเกจโหมด `--onedir` (`dist\PLADAZ\`) |
| **Microsoft Edge WebView2 Runtime** | 155.0.4283.62 | ตรวจพบที่ `C:\Program Files (x86)\Microsoft\EdgeWebView\Application\` |
| **yt-dlp.exe** | 2026.10.21 | รวมอยู่ใน `_internal\bin\yt-dlp.exe` (ขนาด 17,880,111 ไบต์, อัปเดต in-place ได้, `DEC-038`) |
| **FFmpeg** | 9.0.2-full_build-www.gyan.dev (libavcodec 63.1.102) | สำหรับ Remux และ Audio Encoding (รวมอยู่ใน `_internal\bin\ffmpeg.exe`) |
| **mutagen** | 1.48.1 | จัดการแท็ก MP4/M4A Atoms |
| **Pillow (PIL)** | 13.0.0 | ตรวจสอบและแปลงภาพปก 1:1 JPEG 800×800 px |
| **psutil** | 7.2.2 | ตรวจจับไดรฟ์และพื้นที่จัดเก็บ |
| **pytest** | 9.1.1 (pluggy 1.7.0) | Test Runner หลัก |
| **Node.js** | v24.13.0 | ใช้รันชุดทดสอบพฤติกรรม Frontend JS (`tests/test_frontend_js.py`) และคอมไพล์ CSS |

---

## 2. สรุปจำนวนชุดทดสอบอัตโนมัติและเกณฑ์การบันทึกสถานะ

### 2.1 สรุปจำนวนการทดสอบอัตโนมัติ (`pytest`)
- **จำนวนการทดสอบที่รวบรวมได้ทั้งหมด (Collected):** **105 รายการ** (2026-10-24 หลังตรวจทาน Browser Authentication)
- **ผลการรันชุดทดสอบออฟไลน์ทั้งหมด (`.\venv\Scripts\python.exe -m pytest -v -m "not network"`):** **`104 passed`**, `1 deselected` (`0 failed`, 2026-10-24)
  - **Unit Tests (`-m "unit"`):** **66 รายการ** (รวม `tests/unit/test_browser_auth.py`, `tests/unit/test_browser_auth_fixes.py`, `tests/test_ux_static.py`, `tests/test_frontend_js.py`)
  - **Integration Tests (`-m "integration and not e2e"`):** **37 รายการ** (รวม `tests/integration/test_audit_fixes.py`, `tests/integration/test_ux_fixes.py`, `tests/test_phase4_bridge_and_shell.py`)
  - **End-to-End Tests (`-m "e2e"`):** **2 รายการ**
    - ออฟไลน์ E2E (`test_bridge_e2e_full_queue_workflow_and_atom_verification`): **1 passed**
    - เครือข่ายจริง E2E (`test_bridge_e2e_live_network_download`): **1 skipped / deselected** เมื่อไม่ได้กำหนดตัวแปรสภาพแวดล้อม `PLADAZ_TEST_URLS` (รอ URL ทดสอบจากผู้ใช้)

### 2.2 เกณฑ์การบันทึกสถานะ (ตาม Plan 9.3 และ Phase 5 Rules)
สถานะที่อนุญาตให้ใช้ในตารางด้านล่างมีเพียง 4 สถานะเท่านั้น:
1. **`Pass`**: รันทดสอบจริงและผ่านเกณฑ์ พร้อมหลักฐานคำสั่งและผลลัพธ์
2. **`Fail`**: รันทดสอบจริงแล้วพบข้อผิดพลาดหรือไม่ผ่านเกณฑ์
3. **`Blocked`**: ไม่สามารถตัดสินผลขั้นสุดท้ายได้เนื่องจากติดเงื่อนไขภายนอก หรือรายการที่ยังเป็น `TBA` (`TBA-023`, `TBA-026`) หรือรอข้อมูลจากเจ้าของโครงการ
4. **`Not Run`**: ยังไม่ได้รันทดสอบด้วยมือกับอุปกรณ์ฮาร์ดแวร์จริงของผู้ใช้ (เครื่อง Windows สะอาด, Micro SD Card จริง, เครื่องเล่น SNOWSKY ECHO DAP)

---

## 3. Test Inventory & Traceability Matrix (`TC-001` ถึง `TC-033`)

| TC ID | สิ่งที่ทดสอบ | ข้อกำหนดที่ผูก | ประเภท | วิธีการ | ไฟล์ทดสอบ / เครื่องมือ | สถานะ | หลักฐาน / ผลลัพธ์ | วันที่ |
|---|---|---|---|---|---|---|---|:---:|
| **TC-001** | ตรวจสอบแพลตฟอร์มเป้าหมายและการเปิดแอปบน Windows | IR-001, IR-002, IR-015, DEC-018, DEC-046 | Compatibility / E2E | อัตโนมัติ (Smoke) + ผู้ใช้ (Clean Windows) | `dist\PLADAZ\PLADAZ.exe --smoke-test` | **Fail** | การทำงาน: ผู้ใช้รายงาน Pass (2026-10-24) — ทดสอบในโหมดพัฒนา (dev) / ไม่ระบุ build และไม่มีรายละเอียดอุปกรณ์ (รุ่น/เฟิร์มแวร์ ECHO, ความจุ/ระบบไฟล์การ์ด, เครื่อง Windows); เกณฑ์ตัวเลข (DEC-054): `scripts/measure_performance.py` กับ build `a4ce579` (2026-10-24): เปิดแอป (`--smoke-test`) ครั้งแรกหลัง build **5.45 วินาที** (เกณฑ์ ≤ 5 วินาที → ไม่ผ่าน), ครั้งถัดมา 3.01 / 3.19 / 2.88 วินาที; ขั้นหลังดาวน์โหลดเพลง 5 นาที: remux 0.28 วินาที, encode 7.81 วินาที (เกณฑ์ ≤ 30 วินาที → ผ่าน, คัดลอกลงโฟลเดอร์ชั่วคราวในเครื่อง ไม่ใช่การ์ดจริง) — **เจ้าของโครงการยอมรับเป็นข้อจำกัด (DEC-055, 2026-10-24)** | 2026-10-24 |
| **TC-002** | สร้างเส้นทางโฟลเดอร์ (`Album Artist` / `Album`) | IR-010, IR-011, IR-018, DEC-010 | Unit | อัตโนมัติ | `tests/unit/test_folder_organizer.py` | **Pass** | `test_tc002_build_target_path_with_album_artist_and_album` ผ่าน | 2026-10-24 |
| **TC-003** | ไม่ใช้ Track Artist เป็นโฟลเดอร์หลัก | IR-011, IR-018, DEC-010 | Unit | อัตโนมัติ | `tests/unit/test_folder_organizer.py` | **Pass** | `test_tc003_folder_uses_album_artist_not_track_artist` ผ่าน | 2026-10-24 |
| **TC-004** | รองรับ Metadata หลัก (`Title`, `Track Artist`, `Album`, `Album Artist`) | IR-006, IR-016, DEC-008 | Unit | อัตโนมัติ | `tests/unit/test_metadata_rules.py` | **Pass** | `test_tc004_core_metadata_tags_written_and_verified_with_uppercase_art_atom` (`©ART`, `©alb`, `©nam`, `aART` ถูกต้อง) | 2026-10-24 |
| **TC-005** | รองรับลำดับแทร็กและแผ่น (`trkn`, `disk`) | IR-006, IR-016, DEC-008 | Unit | อัตโนมัติ | `tests/unit/test_metadata_rules.py` | **Pass** | `test_tc005_track_number_and_disc_number_atoms` (`trkn`, `disk` tuples ถูกต้อง) | 2026-10-24 |
| **TC-006** | รองรับ Year และ Genre (`©day`, `©gen`) | IR-006, IR-016, DEC-008 | Unit | อัตโนมัติ | `tests/unit/test_metadata_rules.py` | **Pass** | `test_tc006_year_and_genre_atoms` (`©day`, `©gen` ถูกต้อง) | 2026-10-24 |
| **TC-007** | รองรับ Album Art (800×800 JPEG ใน `covr`) | IR-005, IR-016, DEC-008, DEC-021 | Unit | อัตโนมัติ | `tests/unit/test_metadata_rules.py` | **Pass** | `test_tc007_process_cover_800x800_jpeg_and_embed_in_covr_atom` (`covr` atom มี JPEG 800×800) | 2026-10-24 |
| **TC-008** | เลือกปลายทางบนพื้นที่จัดเก็บข้อมูล | IR-008, IR-009, IR-019, DEC-011 | File System / Device | อัตโนมัติ + ผู้ใช้ (การ์ดจริง) | `tests/integration/test_sd_card_manager.py`, `tests/test_phase4_bridge_and_shell.py` | **Pass** | ผู้ใช้รายงาน Pass (2026-10-24) — ทดสอบในโหมดพัฒนา (dev) / ไม่ระบุ build และไม่มีรายละเอียดอุปกรณ์ (รุ่น/เฟิร์มแวร์ ECHO, ความจุ/ระบบไฟล์การ์ด, เครื่อง Windows); ชุดทดสอบอัตโนมัติจำลองผ่าน | 2026-10-24 |
| **TC-009** | ปลายทางไม่พร้อมใช้งาน (Disconnected / Read-only) | IR-008, IR-019, DEC-011 | File System | อัตโนมัติ + ผู้ใช้ (การ์ดจริง) | `tests/integration/test_sd_card_manager.py` | **Pass** | `test_tc009_destination_disconnected_or_read_only_raises_error` คืน `ERR_SDCARD_DISCONNECTED` ถูกต้อง (มีการทดสอบเสริมกับการ์ดจริงใน Checklist E) | 2026-10-24 |
| **TC-010** | พื้นที่ไม่เพียงพอ | IR-019, DEC-011 | File System | อัตโนมัติ | `tests/integration/test_sd_card_manager.py` | **Pass** | `test_tc010_insufficient_free_space_raises_error` คืน `ERR_SDCARD_INSUFFICIENT_SPACE` ถูกต้อง | 2026-10-24 |
| **TC-011** | ไม่มี Metadata บางฟิลด์ (Fallback & Unknown Artist) | IR-006, IR-010, IR-018, DEC-015 | Unit | อัตโนมัติ | `tests/unit/test_folder_organizer.py`, `tests/unit/test_metadata_rules.py` | **Pass** | โฟลเดอร์ fallback เป็น `'Unknown Artist'`, ในแท็กเว้นว่างไว้โดยไม่เติมค่าหลอก | 2026-10-24 |
| **TC-012** | ชื่อโฟลเดอร์/ไฟล์มีอักขระต้องห้ามของ Windows | IR-018, DEC-014, DEC-037 | Unit | อัตโนมัติ | `tests/unit/test_folder_organizer.py` | **Pass** | `test_tc012_windows_forbidden_characters_replaced_with_underscore` แปลง `\ / : * ? " < > \|` เป็น `_` | 2026-10-24 |
| **TC-013** | นโยบายจัดการไฟล์ซ้ำ (Conflict Prompt: Overwrite / Skip / Keep Both) | IR-018, DEC-019, DEC-036, DEC-039 | Unit / Integration | อัตโนมัติ | `tests/unit/test_conflict_resolution.py`, `tests/test_frontend_js.py` | **Pass** | ตรวจก่อนโหลดเสียง รองรับ Overwrite, Skip (ลบออกจากคิว), Keep Both (` (1)`) และกู้คืน Prompt ใน UI ได้เมื่อเปิดแอปใหม่หรือเมื่อคำสั่งล้มเหลว | 2026-10-24 |
| **TC-014** | ตรวจสอบไฟล์ผลลัพธ์ (AAC-LC, M4A, Metadata) | IR-004, IR-020, DEC-012 | Integration | อัตโนมัติ | `tests/unit/test_output_validator.py` | **Pass** | `test_tc014_valid_aac_lc_m4a_with_metadata_and_cover_passes` ผ่าน | 2026-10-24 |
| **TC-015** | อ่านไฟล์บนเครื่องเป้าหมาย (SNOWSKY ECHO DAP) | IR-004, IR-005, IR-006, DEC-020 | Compatibility / Device | ผู้ใช้ (อุปกรณ์จริง) | เครื่องเล่น SNOWSKY ECHO DAP | **Pass** | ผู้ใช้รายงาน Pass (2026-10-24) — ทดสอบในโหมดพัฒนา (dev) / ไม่ระบุ build และไม่มีรายละเอียดอุปกรณ์ (รุ่น/เฟิร์มแวร์ ECHO, ความจุ/ระบบไฟล์การ์ด, เครื่อง Windows); ชุดทดสอบอัตโนมัติจำลองผ่าน | 2026-10-24 |
| **TC-016** | การยกเลิกงานกลางคัน (`Cancel` → `ERR_TASK_CANCELLED`) | IR-017, DEC-042, DEC-049 | Integration | อัตโนมัติ | `tests/integration/test_queue_worker.py`, `tests/test_phase4_bridge_and_shell.py`, `tests/test_frontend_js.py` | **Pass** | `test_tc016_cancel_mid_download_cleans_temp_and_sets_failed_err_task_cancelled` ลบไฟล์ใน Temp หยุดคิวรอ Resume และ UI รับสถานะ `queue_halted` จาก Backend เท่านั้น | 2026-10-24 |
| **TC-017** | การบันทึกข้อผิดพลาดลง Log อย่างรัดกุม | IR-013, DEC-024 | Unit | อัตโนมัติ | `tests/unit/test_logger.py` | **Pass** | `test_tc017_error_logging_contains_required_diagnostic_fields` (มี timestamp, code, context) | 2026-10-24 |
| **TC-018** | การทำงานของ Download Queue (Sequential Worker) | IR-017, DEC-009, DEC-023 | Integration | อัตโนมัติ | `tests/integration/test_queue_worker.py`, `tests/test_frontend_js.py` | **Pass** | `test_tc018_download_queue_sequential_state_transitions` (`Queued` → `Downloading` → `Completed`/`Failed`), อัปเดต DOM เฉพาะแถวที่เปลี่ยน และนับสรุปเฉพาะงานในรอบปัจจุบัน | 2026-10-24 |
| **TC-019** | การตรวจจับการ์ดและการถอด Micro SD Card กลางคัน | IR-019, DEC-011, DEC-041 | Integration / Device | อัตโนมัติ (จำลอง) + ผู้ใช้ (การ์ดจริง) | `tests/integration/test_queue_worker.py`, `tests/integration/test_sd_card_manager.py` | **Pass** | ผู้ใช้รายงาน Pass (2026-10-24) — ทดสอบในโหมดพัฒนา (dev) / ไม่ระบุ build และไม่มีรายละเอียดอุปกรณ์ (รุ่น/เฟิร์มแวร์ ECHO, ความจุ/ระบบไฟล์การ์ด, เครื่อง Windows); ชุดทดสอบอัตโนมัติจำลองผ่าน | 2026-10-24 |
| **TC-020** | การตรวจสอบความถูกต้องของไฟล์ด้วย `OutputValidator` | IR-020, DEC-012, DEC-030 | Unit | อัตโนมัติ | `tests/unit/test_output_validator.py` | **Pass** | `test_tc020_output_validator_rejects_corrupt_non_aac_and_missing_title_files` ปฏิเสธไฟล์ไม่สมบูรณ์ | 2026-10-24 |
| **TC-021** | Automated Regression Testing Pipeline | IR-021, DEC-013, DEC-024, DEC-051 | Regression | อัตโนมัติ | `scripts/run_tests.ps1` (`(unit or integration or fs) and not network`) + git hook `pre-commit` / `pre-push` (`scripts/install_git_hooks.ps1`) | **Pass** | 2026-10-24: แก้ไข `folder_organizer.py` ให้ใช้ Track Artist (ผิด IR-011) แล้วสั่ง `git commit` จริง → hook `pre-commit` รันชุด regression ได้ `6 failed, 65 passed, 1 deselected` ข้อความ `Regression tests failed! commit aborted.` และ `git commit` คืน exit code 1, HEAD ไม่เปลี่ยน (`0afbf62`) จากนั้นคืนไฟล์เดิมและรันชุดเต็มได้ `71 passed, 1 deselected`. ข้อจำกัด: hook อยู่ใน `.git/hooks` (ไม่ถูก version) ต้องรัน `install_git_hooks.ps1` ในทุก clone | 2026-10-24 |
| **TC-022** | ไม่พบปกอัลบั้ม (สวิตซ์ค่าเริ่มต้น `require_cover=False`) | IR-005, IR-020, DEC-031 | Unit | อัตโนมัติ | `tests/unit/test_output_validator.py` | **Pass** | `test_tc022_missing_cover_with_default_switch_passes_with_warning` ผ่านเป็น `Completed` พร้อม Warning | 2026-10-24 |
| **TC-023** | ไม่พบปกอัลบั้ม (สวิตซ์บังคับมีปก `require_cover=True`) | IR-005, IR-020, DEC-031 | Unit / Integration | อัตโนมัติ | `tests/unit/test_output_validator.py`, `tests/integration/test_queue_worker.py` | **Pass** | `test_tc023_missing_cover_with_require_cover_true_fails_validation` ปรับงานเป็น `Failed` ไม่คัดลอกลงการ์ด | 2026-10-24 |
| **TC-024** | การเลือกสตรีมเสียง (`REMUX_AAC` vs `ENCODE_AAC_LC`) | IR-004, IR-016, DEC-006, DEC-033 | Integration | อัตโนมัติ (`ffmpeg.exe` จริง) | `tests/integration/test_audio_pipeline.py` | **Pass** | ทั้ง `test_tc024a_stream_with_aac_lc_uses_remux` และ `test_tc024b_stream_without_aac_encodes_to_aac_lc` ผ่านด้วย `ffmpeg.exe` จริง (ตาม Plan 9.2 ค่า `TBA-027` ไม่บล็อกการทดสอบโดยใช้ค่าเริ่มต้นของ FFmpeg และบันทึกไว้แล้ว; ส่วนการทดสอบผ่านเน็ตจริงรอ URL ใน `PLADAZ_TEST_URLS`) | 2026-10-24 |
| **TC-025** | ชื่อลงท้ายด้วยจุด/ช่องว่าง, อักขระควบคุม และชื่อสงวน Windows | IR-018, DEC-034, DEC-037 | Unit | อัตโนมัติ | `tests/unit/test_folder_organizer.py` | **Pass** | `test_tc025_trailing_dots_spaces_control_chars_and_reserved_names_on_windows` (`CON.mix` → `CON_.mix`, `Hello...` → `Hello___`) | 2026-10-24 |
| **TC-026** | เกณฑ์ยอมรับผลค้นหา iTunes/MusicBrainz | IR-006, DEC-021, DEC-035 | Unit / Integration | อัตโนมัติ | `tests/unit/test_metadata_rules.py`, `tests/integration/test_audio_pipeline.py` | **Blocked** | โครงสร้าง `TemporaryExactMetadataMatcher` และการเรียก iTunes ทำงานได้ถูกต้อง แต่รายละเอียดอัลกอริทึมเทียบชื่อสุดท้ายและ `User-Agent` ของ MusicBrainz ยังติด `TBA-026` | 2026-10-24 |
| **TC-027** | เส้นทางยาวเกินเพดาน Windows `MAX_PATH` (> 259 อักขระ) | IR-002, IR-018, DEC-043 | Unit / Integration | อัตโนมัติ | `tests/unit/test_folder_organizer.py`, `tests/integration/test_queue_worker.py` | **Pass** | `test_tc027_path_exceeding_windows_max_path_raises_err_path_too_long` ตรวจพบก่อนโหลดเสียงและปรับเป็น `Failed` (`ERR_PATH_TOO_LONG`) | 2026-10-24 |
| **TC-028** | Overwrite แล้วการ์ดหลุดกลางคัน (`.pladaz-tmp`) | IR-019, DEC-032, DEC-040 | File System / Device | อัตโนมัติ (จำลอง) + ผู้ใช้ (การ์ดจริง) | `tests/integration/test_sd_card_manager.py` | **Pass** | ผู้ใช้รายงาน Pass (2026-10-24) — ทดสอบในโหมดพัฒนา (dev) / ไม่ระบุ build และไม่มีรายละเอียดอุปกรณ์ (รุ่น/เฟิร์มแวร์ ECHO, ความจุ/ระบบไฟล์การ์ด, เครื่อง Windows); ชุดทดสอบอัตโนมัติจำลองผ่าน | 2026-10-24 |
| **TC-029** | Personal Use Disclaimer | IR-015, DEC-027 | Integration / E2E | อัตโนมัติ + เจ้าของโครงการ | `tests/unit/test_config_store.py`, `ui/index.html` (Board 04) | **Pass** | ข้อความ Disclaimer ฉบับใช้งานอยู่ในบอร์ด 04 แล้ว (DEC-054: เจ้าของโครงการมอบให้เขียน) ตรวจด้วย `test_ui_bundle_offline_no_cdn_and_constraints`; กลไกบันทึก `disclaimer_accepted` ผ่าน `tests/unit/test_config_store.py` | 2026-10-24 |
| **TC-030** | การจัดการ `config.json` และ `history.json` (ปกติและกู้คืนไฟล์เสีย) | IR-013, DEC-023 | Unit / Integration | อัตโนมัติ | `tests/unit/test_config_store.py`, `tests/test_phase4_bridge_and_shell.py` | **Pass** | `test_tc030a`, `test_tc030b` กู้คืนไฟล์เสียเป็น `.corrupt-<timestamp>` และสร้างไฟล์เริ่มต้นใหม่ได้ปลอดภัย | 2026-10-24 |
| **TC-031** | การอัปเดตโมดูล `yt-dlp.exe` | IR-016, DEC-026, DEC-038 | Unit / Integration | อัตโนมัติ | `tests/unit/test_source_adapter.py`, `tests/test_phase4_bridge_and_shell.py` | **Pass** | `test_tc031_update_ytdlp_success_and_failure_rollback` มีระบบ rollback คงไฟล์เดิมเมื่ออัปเดตล้มเหลว | 2026-10-24 |
| **TC-032** | ความเป็นส่วนตัวของ `cookies.txt` ใน Logging | IR-013, DEC-027 | Unit / Security | อัตโนมัติ | `tests/unit/test_logger.py`, `tests/test_phase4_bridge_and_shell.py` | **Pass** | `test_tc032_cookies_and_tokens_never_appear_in_logs_or_structured_error` ปกปิดโทเคนและข้อมูลคุกกี้ใน Log และ StructuredError | 2026-10-24 |
| **TC-033** | ขอบเขต `Apply to all` (Album vs Queue) | IR-018, DEC-044 | Unit | อัตโนมัติ | `tests/unit/test_conflict_resolution.py` | **Pass** | `test_tc033a` (เฉพาะในโฟลเดอร์อัลบั้มเดียวกัน), `test_tc033b` (คลุมงานใหม่และรีเซ็ตเมื่อคิวว่าง) | 2026-10-24 |

---

## 4. สรุปความครอบคลุมข้อกำหนด (Traceability to IR-001 ถึง IR-021)

| Requirement ID | รายละเอียดสังเขป | Test Cases ที่ผูก | สถานะการผูก Test Cases |
|---|---|---|---|
| **IR-001** | ชื่อแอปพลิเคชัน PLADAZ | TC-001 | ผูกครบ (`TC-001` = Fail ที่เกณฑ์เวลาเปิดแอปครั้งแรก 5.45 วินาที; การเปิดบน Windows สะอาดผู้ใช้รายงานผ่าน) |
| **IR-002** | แพลตฟอร์ม Windows | TC-001, TC-027 | ผูกครบ (`TC-027` ผ่าน; `TC-001` ติด `Blocked`) |
| **IR-003** | วัตถุประสงค์ดาวน์โหลดเพลง | TC-018, TC-024 | ผูกครบและผ่านชุดทดสอบอัตโนมัติ |
| **IR-004** | รูปแบบเสียงเป้าหมาย AAC | TC-014, TC-015, TC-020, TC-024 | ผูกครบ (`TC-014`, `TC-020`, `TC-024` ผ่าน; รอ `TC-015` บนเครื่องจริง) |
| **IR-005** | รองรับปกอัลบั้ม (JPEG 800×800) | TC-007, TC-014, TC-015, TC-020, TC-022, TC-023 | ผูกครบ (ส่วนซอฟต์แวร์ผ่านทั้งหมด; รอ `TC-015` บนเครื่องจริง) |
| **IR-006** | รองรับ Metadata 8 ฟิลด์ | TC-004, TC-005, TC-006, TC-011, TC-014, TC-015, TC-026 | ผูกครบ (`TC-004`–`006`, `011`, `014` ผ่าน; `TC-026` ติด `TBA-026`; รอ `TC-015`) |
| **IR-007** | แหล่งเพลง YouTube / YouTube Music | TC-024, TC-031 | ผูกครบและผ่านชุดทดสอบอัตโนมัติ |
| **IR-008** | ปลายทางจัดเก็บบน Micro SD Card | TC-008, TC-009, TC-010, TC-019 | ผูกครบ (ส่วนซอฟต์แวร์ผ่าน; รอทดสอบการ์ดจริง `TC-008`, `TC-019`) |
| **IR-009** | กำหนดโฟลเดอร์ปลายทางได้ | TC-008 | ผูกครบ (ส่วนซอฟต์แวร์ผ่าน; รอทดสอบการ์ดจริง) |
| **IR-010** | จัดระเบียบเพลงเป็นโฟลเดอร์ | TC-002, TC-011, TC-026 | ผูกครบ |
| **IR-011** | โครงสร้างยึด Album Artist / Album | TC-002, TC-003, TC-011 | ผูกครบและผ่านชุดทดสอบอัตโนมัติ |
| **IR-012** | Backend ขยายและเพิ่มฟีเจอร์ได้ | TC-021, TC-026 | ผูกครบ |
| **IR-013** | ยึดหลัก Software Engineering และ Logging สะอาด | TC-017, TC-021, TC-030, TC-032 | ผูกครบและผ่านชุดทดสอบอัตโนมัติ |
| **IR-014** | มีชุด Test Cases ครอบคลุม | TC-001 ถึง TC-033 | ผูกครบทั้ง 33 รายการ |
| **IR-015** | Frontend pywebview + PyInstaller .exe | TC-001, TC-029 | ผูกครบ (`TC-029` = Pass; `TC-001` = Fail ที่เกณฑ์เวลาเปิดแอปครั้งแรก) |
| **IR-016** | ประมวลผลด้วย yt-dlp + FFmpeg + mutagen | TC-004, TC-005, TC-006, TC-007, TC-024, TC-031 | ผูกครบและผ่านชุดทดสอบอัตโนมัติ |
| **IR-017** | Download Queue (4 สถานะหลัก) | TC-016, TC-018 | ผูกครบและผ่านชุดทดสอบอัตโนมัติ |
| **IR-018** | Smart Folder Organizer (กฎชื่อซ้ำ, sanitize, missing) | TC-002, TC-003, TC-011, TC-012, TC-013, TC-025, TC-027, TC-033 | ผูกครบและผ่านชุดทดสอบอัตโนมัติ |
| **IR-019** | SD Card Manager (ตรวจการ์ด, พื้นที่, ถอดการ์ด) | TC-008, TC-009, TC-010, TC-019, TC-028 | ผูกครบ (ส่วนซอฟต์แวร์จำลองผ่าน; รอทดสอบการ์ดจริง) |
| **IR-020** | Output Validator (ตรวจไฟล์ก่อน Completed) | TC-014, TC-020, TC-022, TC-023 | ผูกครบและผ่านชุดทดสอบอัตโนมัติ |
| **IR-021** | Automated Regression Testing Pipeline | TC-021 | ผูกครบและผ่านชุดทดสอบอัตโนมัติ |

---

## 5. หลักฐานการทดสอบเชิงลึก (Deep Verification Evidence)

### 5.1 หลักฐานการรันชุดทดสอบอัตโนมัติและจับ Regression (`TC-021`)
- **คำสั่งรันชุดทดสอบออฟไลน์ทั้งหมด:**
  ```powershell
  .\venv\Scripts\python.exe -m pytest -v -m "not network"
  ```
- **ผลลัพธ์:** `104 passed, 1 deselected in 11.89s` (2026-10-24 ผลล่าสุดจาก pre-commit hook ของ commit `51615c7`; ลำดับ: 58 → 71 หลังรายงานตรวจสอบ → 85 Browser Authentication → 97 UX/UI → 104 ตรวจทาน Browser Authentication)
- **สคริปต์ Regression:** `powershell -ExecutionPolicy Bypass -File .\scripts\run_tests.ps1`
- **การทดลองฉีดบั๊กเพื่อพิสูจน์การจับ Regression:** ทดลองแก้ `SmartFolderOrganizer.resolve_folder_names` ให้ใช้ `track_artist` แทน `album_artist` ชั่วคราว แล้วรัน `run_tests.ps1` ระบบตรวจจับความผิดพลาดได้ทันทีที่ `test_tc003_folder_uses_album_artist_not_track_artist` และคืน Exit Code `1` ก่อน Revert โค้ดกลับสู่สถานะปกติและรันผ่านครบ

### 5.2 หลักฐานการตรวจสอบพฤติกรรม Frontend JS และสัญญาเชื่อมต่อ Bridge (`tests/test_frontend_js.py`)
ทดสอบด้วย Node.js VM harness กับไฟล์ [`ui/js/bridge.js`](file:///e:/Doc/Code/randombullshit/PLADAZV2/ui/js/bridge.js) และ [`ui/js/app.js`](file:///e:/Doc/Code/randombullshit/PLADAZV2/ui/js/app.js) ยืนยันว่า:
1. `submitConflictChoice` ไม่ปิดหน้าต่างและไม่ล้าง `state.pendingConflict` หาก `resolve_conflict` ล้มเหลว และสามารถกู้คืนหน้าต่าง Conflict Prompt ได้เมื่อเปิดแอปใหม่ (`get_initial_state().pending_conflict`)
2. คำสั่ง UI ทั้งหมดตรวจสอบ `res.success` และแสดงแบนเนอร์แจ้งเตือนเมื่อล้มเหลว โดยไม่แอบเปลี่ยน `queueHalted` เองก่อนได้รับค่าจาก Backend
3. `browseDestinationFolder()` และ `selectCookiesFile()` ไม่รับพารามิเตอร์พาธจากฝั่งหน้าเว็บ การล้างคุกกี้ใช้ `clearCookiesFile()` และการเลือกการ์ดใช้ `selectDetectedDrive(driveRoot)` ซึ่งตรวจใน Backend เท่านั้น
4. เหตุการณ์ `task:progress` อัปเดตเฉพาะแถวของงานนั้นโดยไม่เขียนทับ `innerHTML` ของรายการคิวทั้งหมด
5. สรุปผลเมื่อจบคิวนับเฉพาะงานที่อยู่ในรอบการทำงานปัจจุบัน (`activeRunTaskIds`)
6. หน้ารายละเอียดเพลงไม่เดาสถานะ Validator เป็น `PASS` เมื่อไม่มีข้อมูล และป้าย `covr` แสดงตามค่า `has_cover` จริง

### 5.3 หลักฐานชื่อ MP4 Atoms ที่เขียนจริง (อ่านด้วย `mutagen.mp4.MP4` ใน `tests/e2e/test_bridge_e2e.py`)
- `\xa9nam` (`©nam`): `["E2E Solo Track"]` (Title)
- `\xa9ART` (`©ART`): `["Featured Artist"]` (Track Artist)
- `aART`: `["Main Album Artist"]` (Album Artist)
- `\xa9alb` (`©alb`): `["Solo Album"]` (Album)
- `trkn`: `[(1, 0)]` (Track 1)
- `disk`: `[(1, 0)]` (Disc 1)
- `\xa9day` (`©day`): `["2026"]` (Year)
- `\xa9gen` (`©gen`): `["Electronic / Ambient"]` (Genre)
- `covr`: `MP4Cover.FORMAT_JPEG` ขนาด `(800, 800)` px 1:1 Aspect Ratio

### 5.4 ค่าแฮชและขนาดของไฟล์แจกจ่ายล่าสุด (Release Binaries SHA-256)
- **ที่มาของ build:** branch `main` ที่ commit `a4ce579` (working tree สะอาด) สั่ง `.\venv\Scripts\pyinstaller.exe --noconfirm --clean pladaz.spec` ด้วย PyInstaller 6.22.3 วันที่ 2026-10-24 แล้วคัดลอก `README.md` และ `LICENSE-THIRD-PARTY.txt` เข้าโฟลเดอร์ (spec ไม่ได้คัดลอกให้) — build นี้มี Browser Authentication, UX/UI fixes และข้อความ Disclaimer แล้ว
- **ตรวจหลัง build:** ไฟล์ใน `_internal\ui\` (`index.html`, `js/app.js`, `js/bridge.js`, `app.built.css`) ตรงกับต้นฉบับใน repo; `PLADAZ.exe --smoke-test` คืน exit code `0` ทุกครั้ง (4 ครั้ง) จากนั้นลบ `config.json`, `history.json`, `logs\`, `temp\` ที่ smoke test สร้างออก
- **ผลวัดเกณฑ์ประสิทธิภาพ (DEC-054):** `scripts/measure_performance.py` กับ build `a4ce579` (2026-10-24): เปิดแอป (`--smoke-test`) ครั้งแรกหลัง build **5.45 วินาที** (เกณฑ์ ≤ 5 วินาที → ไม่ผ่าน), ครั้งถัดมา 3.01 / 3.19 / 2.88 วินาที; ขั้นหลังดาวน์โหลดเพลง 5 นาที: remux 0.28 วินาที, encode 7.81 วินาที (เกณฑ์ ≤ 30 วินาที → ผ่าน, คัดลอกลงโฟลเดอร์ชั่วคราวในเครื่อง ไม่ใช่การ์ดจริง)
- **`dist\PLADAZ\PLADAZ.exe`** (รวม Python code ใน PYZ archive):
  - ขนาด: `5,917,943` ไบต์ (`~5.92 MB`)
  - SHA-256: `AC31AA9A15187903C2E3792C352F1630F59B394251FA8C92580DA5025E4C601C`
- **`dist\PLADAZ\_internal\bin\yt-dlp.exe`** (2026.10.21):
  - ขนาด: `17,880,111` ไบต์ (`~17.88 MB`)
  - SHA-256: `33121D192D706E62F684A06F80918E3F3A8BA52AC3A65213B6951C39C7D9F555`
- **`dist\PLADAZ\_internal\bin\ffmpeg.exe`** (9.0.2 gyan.dev full_build):
  - ขนาด: `227,823,104` ไบต์ (`~227.8 MB`)
  - SHA-256: `589E50B766D251AFDF181DD664D40BD94407E200B019989FD7468C7D118A28D0`
- **ข้อจำกัด:** ค่าแฮชไม่ครอบคลุมไฟล์อื่นใน `_internal\` (UI assets, DLL); ผลทดสอบเครื่องจริงที่ผู้ใช้รายงานทำในโหมดพัฒนา ไม่ใช่ build นี้

### 5.5 ผลการทดสอบระบบ Browser Authentication & Consent (Option C — DEC-052)
- **Unit Tests (`tests/unit/test_browser_auth.py` — 13 passed):**
  - ตรวจสอบรายชื่อเบราว์เซอร์และป้ายกำกับ (`is_supported_browser`, `browser_label`)
  - อัลกอริทึมการแนะนำเบราว์เซอร์: แนะนำ Firefox ก่อน Chromium เพื่อหลีกเลี่ยง DPAPI / App-Bound Encryption บน Windows
  - การจำลอง Windows Registry (`HKLM/StartMenuInternet`, `HKCU/UserChoice`) ร่วมกับโฟลเดอร์โปรไฟล์ผู้ใช้จำลอง
  - การแปลผลเอาต์พุต yt-dlp เป็นสถานะภาษาง่าย: `readable`, `encryption_blocked`, `browser_locked`, `profile_not_found`, `permission_denied`, `unsupported`
  - ตรวจสอบคลาสและรหัสข้อผิดพลาด `ERR_SOURCE_AUTH_REQUIRED` และ `ERR_BROWSER_COOKIES_FAILED`
- **Bridge Integration Tests (`tests/test_phase4_bridge_and_shell.py` — 7 passed):**
  - ตรวจสอบ `detect_supported_browsers()`, `test_browser_cookies()`, `select_browser_cookies()`, `clear_browser_cookies()`
  - ตรวจสอบการปฏิเสธเบราว์เซอร์ที่ไม่รองรับ (`ERR_CONFIG_INVALID`)
  - ตรวจสอบการบันทึกสถานะ `browser_cookies_enabled` และ `browser_cookies_name` ลง `config.json` เฉพาะเมื่อตรวจสอบผ่าน
- **Frontend DOM Harness Tests (`tests/test_frontend_js.py` — 2 passed):**
  - ตรวจสอบการเรนเดอร์ dropdown เบราว์เซอร์และการแสดงป้าย `RECOMMENDED`
  - ตรวจสอบการเปิดหน้าต่าง Explicit Consent Modal (`modal-browser-consent`) และการโฟกัสปุ่ม `CANCEL` ก่อน
  - ตรวจสอบการปิดหน้าต่างด้วยปุ่ม Cancel และปุ่ม Esc
  - ตรวจสอบการกด `CONTINUE` ที่เรียก `select_browser_cookies`, อัปเดตสถานะป้ายเป็น `✓ ACTIVE: FIREFOX`, และแสดงข้อความชี้แจงผล
  - ตรวจสอบการกด `REMOVE` เพื่อยกเลิกการเชื่อมต่อคุกกี้
  - ตรวจสอบว่า `TEST AGAIN` เปิดหน้าต่างยินยอมก่อน และไม่เรียก `test_browser_cookies` จนกว่าจะกด Continue; กด Cancel แล้วแสดง "No cookies were read"; dropdown แสดง `not detected` / `installed, no profile found`
- **Regression Tests จากการตรวจทาน (`tests/unit/test_browser_auth_fixes.py`, 2026-10-24):**
  - ความล้มเหลวอื่นหลังอ่านคุกกี้ได้แล้ว (เช่น `Video unavailable`) ไม่ถูกนับเป็น `ERR_BROWSER_COOKIES_FAILED`
  - `check_browser_cookies` ไม่ล้มเมื่อเกิดข้อผิดพลาดที่ไม่คาดคิด (เดิมเรียก `logger.warn` ที่ไม่มีอยู่)
  - ข้อความเบราว์เซอร์ที่ไม่รองรับแสดงรายชื่อที่รองรับครบ และข้อความในหน้าต่างยินยอมตรงกับการทำงานจริง
  - `real_binaries`: รัน `yt-dlp` 2026.10.21 จริงกับโปรไฟล์ Firefox จำลองที่สร้างในเทสต์ ได้สถานะ `readable` (1 คุกกี้) และ `profile_not_found` ตามคาด และผลลัพธ์ไม่มีค่าคุกกี้
  - `[Unverified]` ยังไม่ได้ทดสอบกับเบราว์เซอร์จริงที่ลงชื่อเข้าใช้ YouTube

---

## 6. รายการทดสอบด้วยมือสำหรับผู้ใช้ (Manual Hardware Verification Checklists)

> **หมายเหตุสำคัญ:** รายการด้านล่างต้องทดสอบกับเครื่องและอุปกรณ์จริงของผู้ใช้ ห้ามผู้ช่วย AI กรอกผลแทน

### Checklist D: ทดสอบ `.exe` บนเครื่อง Windows สะอาด (ไม่มี Python)
- [ ] 1. คัดลอกทั้งโฟลเดอร์ `dist\PLADAZ\` ไปยังเครื่อง Windows สะอาด (หรือ Windows Sandbox)
- [ ] 2. ลบหรือเปลี่ยนชื่อ `_internal\bin\yt-dlp.exe` ชั่วคราว แล้วดับเบิลคลิก `PLADAZ.exe` → ตรวจว่าหน้าต่างแจ้งเตือน `First-Run Setup · External Binary Required (yt-dlp.exe)` (บอร์ด 09) ปรากฏขึ้นอย่างถูกต้อง
- [ ] 3. วาง `yt-dlp.exe` กลับคืน (หรือกด `CHECK AGAIN` / `LOCATE FILE…`) แล้วกด `OPEN PLADAZ ›` → หน้าต่าง `Personal Use Disclaimer` (บอร์ด 04) แสดงขึ้นในการเปิดครั้งแรก (`TC-029`)
- [ ] 4. ติ๊กถูกยอมรับเงื่อนไขและกด `ACCEPT & CONTINUE` → เข้าสู่หน้าจอหลักโดยไม่มีหน้าต่างคอนโซล Command Prompt สีดำเด้งขึ้นมา
- [ ] 5. ปิดแอปแล้วเปิดใหม่ → ตรวจว่า `config.json` คงอยู่ และหน้าต่าง Disclaimer ไม่แสดงซ้ำ
- [ ] 6. ตรวจสอบว่าไฟล์ `config.json`, `history.json`, โฟลเดอร์ `temp/` และโฟลเดอร์ `logs/` ถูกสร้างอยู่ข้าง `PLADAZ.exe` อย่างเรียบร้อย

### Checklist E: ทดสอบกับ Micro SD Card จริง (ผู้ใช้ทำ — ใช้การ์ดทดสอบ)
> **คำเตือนความปลอดภัย:** การทดสอบถอดการ์ดมีความเสี่ยงต่อข้อมูล กรุณาใช้การ์ดทดสอบหรือสำรองข้อมูลสำคัญออกก่อนเสมอ
- [ ] 1. เสียบการ์ดเข้าคอมพิวเตอร์ → ในแอป PLADAZ เปิดหน้า `Storage` กด `↻ SCAN REMOVABLE DRIVES` แล้วกด `USE THIS CARD` (`TC-008`) ตรวจว่าแถบสถานะแสดงความจุและป้าย `READY`
- [ ] 2. ดาวน์โหลด 1 เพลง → รันคำสั่ง `.\venv\Scripts\python.exe scripts\verify_sd_card.py <DRIVE:>` เพื่อตรวจโครงสร้างโฟลเดอร์และ MP4 Atoms บนการ์ด
- [ ] 3. **TC-009 / TC-019 (ถอดการ์ดระหว่างดาวน์โหลด):** วางลิงก์เพลงยาว กด `▶ START QUEUE` ขณะกำลังดาวน์โหลด ให้ดึงการ์ดรีดเดอร์ออก → แอปต้องแจ้งเตือนการ์ดหลุด (`ERR_SDCARD_DISCONNECTED`) งานเปลี่ยนเป็น `Failed` คิวหยุดชั่วคราว และไม่รายงานว่าสำเร็จผิดพลาด เมื่อเสียบการ์ดกลับแล้วกด `▶ RESUME QUEUE` สามารถทำงานต่อได้
- [ ] 4. **TC-028 (Overwrite แล้วถอดการ์ด):** ดาวน์โหลดเพลงซ้ำ เลือก `OVERWRITE` แล้วดึงการ์ดออกขณะกำลังคัดลอกทับ → ไฟล์เพลงเดิมบนการ์ดยังคงอยู่ ไม่เสียหาย และไม่มีไฟล์ `.pladaz-tmp` ตกค้าง

### Checklist F: ทดสอบความเข้ากันได้กับเครื่อง SNOWSKY ECHO DAP (`TC-015`)
- รุ่นเครื่อง: SNOWSKY ECHO DAP (Dual Cirrus CS43198 DAC)
- เฟิร์มแวร์ของเครื่อง: __________________
- ระบบไฟล์ของการ์ด (FAT32 / exFAT): __________________
- นำ Micro SD Card ไปเสียบในเครื่อง SNOWSKY ECHO DAP แล้วตรวจสอบ:
  - [ ] 1. เครื่องเล่นอ่านพบเพลงและเล่นเสียงได้อย่างราบรื่น ไม่มีสะดุดหรือเสียงกระตุก
  - [ ] 2. หน้าจอแสดงชื่อเพลง (`Title`) ถูกต้อง (รวมถึงภาษาไทยและอักขระพิเศษ)
  - [ ] 3. แสดงชื่อศิลปิน (`Artist` / `Album Artist`) และชื่ออัลบั้ม (`Album`) ถูกต้อง
  - [ ] 4. แสดงภาพปกอัลบั้ม 800×800 JPEG บนหน้าจอเครื่องเล่นได้อย่างถูกต้อง
  - [ ] 5. ลำดับเพลงในอัลบั้มเรียงตาม Track Number ถูกต้อง
  - [ ] 6. เพลงที่ไม่มีภาพปก (หากมี) แสดงไอคอนเริ่มต้นของเครื่องเล่นโดยไม่ค้าง
