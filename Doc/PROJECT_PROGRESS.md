# PLADAZ — บันทึกความคืบหน้าโครงการ (Project Progress Log)

> **เอกสารติดตามความคืบหน้าและหลักฐานการพัฒนา (Project Progress & Verification Log)**
>
> **ชื่อโครงการ:** PLADAZ  
> **อัปเดตล่าสุด:** 2026-10-23  
> **เอกสารอ้างอิงหลัก:** [`Doc/IMPLEMENT_PLAN.md`](file:///e:/Doc/Code/randombullshit/PLADAZV2/Doc/IMPLEMENT_PLAN.md) (v2.3) และ [`Doc/SYSTEM_DESIGN.md`](file:///e:/Doc/Code/randombullshit/PLADAZV2/Doc/SYSTEM_DESIGN.md) (v2.2)  
> **ระยะปัจจุบัน:** เสร็จสิ้น **Phase 0**, **Phase 1**, และ **Phase 2 (สร้างแกนระบบ)** — พร้อมเริ่ม **Phase 3 (เชื่อมต่อกระบวนการเพลง)**

---

## 1. ภาพรวมสถานะรายระยะ (Phase Overview)

| ระยะ (Phase) | ชื่อระยะ | สถานะ | สรุปผลงานหลัก |
|---|---|---|---|
| **Phase 0** | ยืนยันข้อกำหนด (Requirements & Decisions) | **เสร็จสิ้น** | ยืนยัน `IR-001`–`IR-021`, บันทึกการตัดสินใจ `DEC-001`–`DEC-044`, แยกเอกสาร UI Design (`DEC-028`), และคงสถานะ `TBA` เฉพาะ `TBA-023`, `TBA-026`, `TBA-027` |
| **Phase 1** | ออกแบบระบบเชิงเทคนิค (System Design) | **เสร็จสิ้น** | จัดทำ [`Doc/SYSTEM_DESIGN.md`](file:///e:/Doc/Code/randombullshit/PLADAZV2/Doc/SYSTEM_DESIGN.md) ครอบคลุมสถาปัตยกรรม 3 ชั้น (`ui`/`bridge`/`services`+`domain`), Data Models, Module Contracts, State Machine, Error Codes และ Traceability Matrix |
| **Phase 2** | สร้างแกนระบบ (Core Backend & Unit/Integration Tests) | **เสร็จสิ้น** | พัฒนาแพ็กเกจ `pladaz` (`domain/` + 6 โมดูลใน `services/`) พร้อมสภาพแวดล้อม `venv` และชุดทดสอบอัตโนมัติ `pytest` ผ่านครบ **34/34 รายการ** (`0 failed`, `0 skipped`) |
| **Phase 3** | เชื่อมต่อกระบวนการเพลง (Download, Audio & Queue) | **รอดำเนินการ** | พัฒนา `DownloadSourceAdapter` (`yt-dlp.exe`), `AudioProcessingService` (`ffmpeg.exe`), `DownloadQueueManager` (Sequential Worker + Conflict Resolution + Cancel/Resume) และ HTTP Client สำหรับ iTunes/MusicBrainz |
| **Phase 4** | พัฒนา Frontend และ App Shell | **รอดำเนินการ** | พัฒนา `BridgeAPI`, `EventDispatcher`, `main.py`, หน้าบ้าน HTML/JS + Tailwind CSS (build ล่วงหน้าตาม `DEC-029`) และแพ็กเกจด้วย PyInstaller |
| **Phase 5** | ตรวจสอบและเตรียมใช้งาน (QA & Release) | **รอดำเนินการ** | ทดสอบ End-to-End, ทดสอบ `.exe` บน Clean Windows, ทดสอบกับ Micro SD Card จริง และทดสอบบนเครื่องเล่นจริง **SNOWSKY ECHO DAP** (`TC-015`) |

---

## 2. บันทึกสิ่งที่ดำเนินการเสร็จแล้วใน Phase 0 และ Phase 1

### 2.1 Phase 0 — การยืนยันข้อกำหนดและแก้ไขจุดขัดแย้ง
- ยืนยันข้อกำหนดหลัก `IR-001` ถึง `IR-021` และบันทึกการตัดสินใจ `DEC-001` ถึง `DEC-044` ใน [`Doc/IMPLEMENT_PLAN.md`](file:///e:/Doc/Code/randombullshit/PLADAZV2/Doc/IMPLEMENT_PLAN.md)
- ปิดประเด็น Open Decisions (`OD-01` ถึง `OD-10`):
  - กฎ Sanitizer 4 ขั้นตอนที่เข้มงวดขึ้น (`DEC-037`, `TC-025`)
  - การแยก `yt-dlp.exe` วางข้าง `.exe` เพื่อให้อัปเดตแยกได้อิสระ (`DEC-038`, `TC-031`)
  - พฤติกรรม `Skip` เอางานออกจากคิวโดยไม่เพิ่มสถานะที่ 5 และไม่ดาวน์โหลดเสียง (`DEC-039`, `TC-013`)
  - การเขียนทับไฟล์บนการ์ด (`Overwrite`) ผ่านไฟล์ชั่วคราว `.pladaz-tmp` ก่อน `os.replace` (`DEC-040`, `TC-028`)
  - การตรวจสถานะการ์ดเป็นระยะระหว่างทำงาน (`DEC-041`, `TC-019`)
  - การควบคุมคิวแบบแมนนวล (`Start` / `Cancel` $\rightarrow$ `Failed` รหัส `ERR_TASK_CANCELLED` / `Resume`) (`DEC-042`, `TC-016`)
  - การตรวจจับเส้นทางยาวเกินเพดาน Windows `MAX_PATH` (`> 259` อักขระ $\rightarrow$ `ERR_PATH_TOO_LONG`) (`DEC-043`, `TC-027`)
  - ขอบเขตของ `Apply to all in this album` (ยึดโฟลเดอร์ `<Album Artist>/<Album>` หลัง sanitize) และ `Apply to all in queue` (มีผลตลอดรอบคิวจนกว่าคิวจะว่าง) (`DEC-044`, `TC-033`)

### 2.2 Phase 1 — การออกแบบระบบเชิงเทคนิค
- จัดทำเอกสาร [`Doc/SYSTEM_DESIGN.md`](file:///e:/Doc/Code/randombullshit/PLADAZV2/Doc/SYSTEM_DESIGN.md) กำหนดโครงสร้างโปรเจกต์, Data Classes, Enums, Protocols, Sequence Diagram, State Machine, ตารางรหัสข้อผิดพลาด (`ErrorCode`) และ Traceability Matrix เชื่อมโยง `IR` $\leftrightarrow$ `DEC/TBA` $\leftrightarrow$ โมดูล $\leftrightarrow$ `TC-001` ถึง `TC-033`

---

## 3. บันทึกสิ่งที่ดำเนินการเสร็จแล้วใน Phase 2 — สร้างแกนระบบ (2026-10-23)

### 3.1 สภาพแวดล้อมและโครงสร้างโปรเจกต์ (ขั้น A)
- **สภาพแวดล้อมเสมือน (`venv`):** Python `3.13.5` บน Windows 11 (`win32`)
- **แพ็กเกจที่ติดตั้ง:** `pladaz==1.0.0` (editable install), `mutagen==1.48.1`, `Pillow==13.0.0`, `psutil==7.2.2`, `pytest==9.1.1`
- **ไฟล์โครงสร้างและคอนฟิกโปรเจกต์:**
  - [`pyproject.toml`](file:///e:/Doc/Code/randombullshit/PLADAZV2/pyproject.toml)
  - [`requirements.txt`](file:///e:/Doc/Code/randombullshit/PLADAZV2/requirements.txt)
  - [`src/pladaz/__init__.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/src/pladaz/__init__.py) (`__version__ = "1.0.0"`)

### 3.2 โมดูลที่พัฒนาเสร็จใน Phase 2 (ขั้น A → E)

| ลำดับ | โมดูล / ไฟล์ | หน้าที่หลักและข้อกำหนดที่รองรับ |
|---|---|---|
| **A1** | [`src/pladaz/domain/enums.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/src/pladaz/domain/enums.py) | นิยาม `TaskStatus` (4 สถานะตาม `IR-017`), `ConflictAction`, `ConflictScope`, `AudioProcessMode`, `Stage` |
| **A2** | [`src/pladaz/domain/models.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/src/pladaz/domain/models.py) | นิยาม Dataclasses ครบตาม `SYSTEM_DESIGN.md` 2.2 (`TrackMetadata`, `RawSourceEntry`, `AudioFormat`, `RawTrackInfo`, `StreamPlan`, `ExternalMetadata`, `UpdateResult`, `ValidationResult`, `SDCardStatus`, `StructuredError`, `TrackTask`, `HistoryEntry`) โดยไม่ผูกกับไลบรารีภายนอก |
| **A3** | [`src/pladaz/domain/errors.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/src/pladaz/domain/errors.py) | นิยามรหัส `ErrorCode` ทั้งหมดตาม `SYSTEM_DESIGN.md` 4.1 และคลาส Exception (`PladazError`, `PathTooLongError`, `MetadataTaggingError`, `SDCardDisconnectedError`, `SDCardInsufficientSpaceError`, `SDCardVerifyFailedError`) |
| **A4** | [`src/pladaz/domain/interfaces.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/src/pladaz/domain/interfaces.py) | นิยาม `MetadataMatcherProtocol` (แยก `TBA-026`), `ExternalMetadataFetcherProtocol`, และ `DriveProbeProtocol` |
| **A5** | [`src/pladaz/services/logger.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/src/pladaz/services/logger.py) | `PladazLogger` (`RotatingFileHandler` ปรับขนาดและจำนวนสำรองได้) พร้อม `SensitiveDataFilter` และ `build_safe_structured_error` ป้องกันข้อมูลคุกกี้/โทเคนจาก `cookies.txt` หลุดลง Log หรือ Error details (`TC-017`, `TC-032`) |
| **A6** | [`src/pladaz/services/config_store.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/src/pladaz/services/config_store.py) | `ConfigHistoryStore` อ่าน-เขียน `config.json` และ `history.json` แบบ Atomic (`.tmp` + `fsync` + `os.replace`) พร้อมสำรองไฟล์เสียเป็น `*.corrupt-<timestamp>` และรีเซ็ตเป็นค่าเริ่มต้น (`TC-029`, `TC-030`) |
| **B** | [`src/pladaz/services/folder_organizer.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/src/pladaz/services/folder_organizer.py) | `SmartFolderOrganizer`: 4-step `sanitize_component` (`DEC-037`), `resolve_folder_names` (`IR-011`, `DEC-015`, `DEC-022`), `build_target_path`, ตรวจความยาวเส้นทาง `> 259` อักขระ (`ERR_PATH_TOO_LONG` ตาม `DEC-043`), `check_conflict`, และ `keep_both_path` (`TC-002`, `TC-003`, `TC-011`–`TC-013`, `TC-025`–`TC-027`) |
| **C** | [`src/pladaz/services/metadata_service.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/src/pladaz/services/metadata_service.py) | `MetadataAlbumArtService`: `resolve_metadata` & `enrich_from_external` (ตามกฎ Plan 7.3 และ `DEC-035` ผ่าน `MetadataMatcherProtocol`), `process_cover` (`Pillow` $\rightarrow$ RGB $\rightarrow$ 1:1 Center Crop $\rightarrow$ 800x800 JPEG ตาม `DEC-021`), และ `write_m4a_tags` (`mutagen.mp4` UTF-8) (`TC-004`–`TC-007`, `TC-011`, `TC-026`) |
| **D** | [`src/pladaz/services/sd_card_manager.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/src/pladaz/services/sd_card_manager.py) | `WindowsDriveProbe` และ `SDCardManager`: ตรวจจับไดรฟ์ถอดได้, ตรวจพื้นที่ว่าง, `is_card_present` (`DEC-041`), `copy_and_verify` ด้วย `flush()` + `os.fsync()` + ตรวจขนาดและเปิดอ่านด้วย `mutagen` (`DEC-032`), ลบไฟล์ค้างเมื่อการ์ดหลุด (`TC-019`), และเขียนทับผ่าน `.pladaz-tmp` + `os.replace` (`DEC-040`, `TC-028`) |
| **E** | [`src/pladaz/services/output_validator.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/src/pladaz/services/output_validator.py) | `OutputValidator`: ตรวจขนาดไฟล์และการเปิดอ่านด้วย `mutagen.mp4`, ตรวจ codec `mp4a.40.2` (AAC-LC) และ `length > 0`, ตรวจแท็กบังคับ `©nam` (`Title` ตาม `DEC-030`), และตรวจภาพปก `covr` ตามสวิตซ์ `require_cover` (`DEC-031`, `TC-014`, `TC-020`, `TC-022`, `TC-023`) |

---

## 4. หลักฐานการทดสอบอัตโนมัติ (`pytest`) และสถานะ Test Cases ทั้งหมด

### 4.1 สรุปผลการรัน `pytest` (ขั้น F)
- **คำสั่ง:** `.\venv\Scripts\pytest.exe`
- **จำนวนการทดสอบทั้งหมด:** **34 รายการ** (ใน 7 ไฟล์ทดสอบ)
- **ผลลัพธ์:** **`34 passed in 0.49s`** (`0 failed`, `0 skipped`)

| ไฟล์ทดสอบ | จำนวน Test Functions | ผลลัพธ์ | ขอบเขตที่ทดสอบ |
|---|---|---|---|
| [`tests/unit/test_logger.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/tests/unit/test_logger.py) | 3 | **3 Passed** | `TC-017`, `TC-032`, และการหมุนไฟล์ Log (`RotatingFileHandler`) |
| [`tests/unit/test_config_store.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/tests/unit/test_config_store.py) | 3 | **3 Passed** | `TC-029` (ส่วนบันทึก config), `TC-030` (อ่าน-เขียนปกติและกู้คืนไฟล์ JSON เสีย) |
| [`tests/unit/test_folder_organizer.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/tests/unit/test_folder_organizer.py) | 8 | **8 Passed** | `TC-002`, `TC-003`, `TC-011` (ส่วนโฟลเดอร์), `TC-012`, `TC-013` (ส่วนคำนวณชื่อซ้ำ), `TC-025`, `TC-026` (ส่วนโฟลเดอร์), `TC-027` |
| [`tests/unit/test_metadata_rules.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/tests/unit/test_metadata_rules.py) | 7 | **7 Passed** | `TC-004`, `TC-005`, `TC-006`, `TC-007`, `TC-011` (ส่วนแท็ก), `TC-026` (ผ่าน Fake Matcher), และกรณี API เสริมล้มเหลว |
| [`tests/unit/test_output_validator.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/tests/unit/test_output_validator.py) | 5 | **5 Passed** | `TC-014`, `TC-020`, `TC-022`, `TC-023`, และกรณีข้อมูลภาพปกใน `covr` เสียหาย |
| [`tests/integration/test_sd_card_manager.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/tests/integration/test_sd_card_manager.py) | 6 | **6 Passed** | `TC-008` (ส่วน Logic/Fake), `TC-009`, `TC-010`, `TC-019`, `TC-028`, และกรณี Verify ขนาดไฟล์ไม่ตรง |
| [`tests/integration/test_core_pipeline.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/tests/integration/test_core_pipeline.py) | 2 | **2 Passed** | `TC-021` (บูรณาการแกนระบบครบวงจร) และการตรวจ AST ยืนยันว่า `domain/` ไม่ import ไลบรารีต้องห้าม |

### 4.2 ตารางสถานะ Test Cases (`TC-001` ถึง `TC-033`)

| TC ID | ชื่อการทดสอบ | สถานะปัจจุบัน | หลักฐาน / หมายเหตุ |
|---|---|---|---|
| **TC-001** | เปิดใช้งานบน Windows | **Not Run** | รอพัฒนา UI และ App Shell (`main.py`) ใน Phase 4 |
| **TC-002** | สร้างเส้นทางโฟลเดอร์ (`Album Artist` / `Album`) | **Pass** | `test_tc002_build_target_path_with_album_artist_and_album` |
| **TC-003** | ไม่ใช้ `Track Artist` เป็นโฟลเดอร์หลัก | **Pass** | `test_tc003_folder_uses_album_artist_not_track_artist` |
| **TC-004** | รองรับ Metadata หลัก (`Title`, `Track Artist`, `Album`, `Album Artist`) | **Pass** | `test_tc004_core_metadata_tags_written_and_verified_with_uppercase_art_atom` |
| **TC-005** | รองรับลำดับแทร็กและแผ่น (`trkn`, `disk`) | **Pass** | `test_tc005_track_number_and_disc_number_atoms` |
| **TC-006** | รองรับ `Year` และ `Genre` (`©day`, `©gen`) | **Pass** | `test_tc006_year_and_genre_atoms` |
| **TC-007** | รองรับ `Album Art` (800x800 JPEG ใน `covr`) | **Pass** | `test_tc007_process_cover_800x800_jpeg_and_embed_in_covr_atom` |
| **TC-008** | เลือกปลายทาง | **Partial Pass** | ผ่านส่วน `SDCardManager` (`test_tc008`); รอเชื่อม Dialog เลือกโฟลเดอร์ใน Phase 4 และการ์ดจริงใน Phase 5 |
| **TC-009** | ปลายทางไม่พร้อมใช้งาน | **Pass** | `test_tc009_destination_disconnected_or_read_only_raises_error` |
| **TC-010** | พื้นที่ไม่เพียงพอ | **Pass** | `test_tc010_insufficient_free_space_raises_error` |
| **TC-011** | ไม่มี Metadata บางฟิลด์ | **Pass** | ผ่านทั้งส่วนแท็ก (`test_metadata_rules.py`) และส่วนโฟลเดอร์ `'Unknown Artist'` (`test_folder_organizer.py`) |
| **TC-012** | ชื่อโฟลเดอร์มีอักขระต้องห้าม | **Pass** | `test_tc012_windows_forbidden_characters_replaced_with_underscore` |
| **TC-013** | นโยบายจัดการไฟล์ซ้ำ | **Partial Pass** | ผ่านส่วน `check_conflict` และ `keep_both_path` (`test_tc013`); รอส่วนคิว (`Skip`/Dialog) ใน Phase 3–4 |
| **TC-014** | ตรวจสอบไฟล์ผลลัพธ์ | **Pass** | `test_tc014_valid_aac_lc_m4a_with_metadata_and_cover_passes` |
| **TC-015** | อ่านไฟล์บนเครื่องเป้าหมาย (SNOWSKY ECHO DAP) | **Not Run** | ต้องทดสอบด้วยมือบนเครื่องเล่นจริงใน Phase 5 |
| **TC-016** | การยกเลิก/ความล้มเหลวกลางทาง (`Cancel` $\rightarrow$ `ERR_TASK_CANCELLED`) | **Not Run** | รอพัฒนา `DownloadQueueManager` ใน Phase 3 |
| **TC-017** | การบันทึกข้อผิดพลาดลง Log | **Pass** | `test_tc017_error_logging_contains_required_diagnostic_fields` |
| **TC-018** | การทำงานของ Download Queue | **Not Run** | รอพัฒนา `DownloadQueueManager` ใน Phase 3 |
| **TC-019** | การตรวจจับการ์ดและการถอด Micro SD Card | **Partial Pass** | ผ่านส่วนตรวจจับการหลุดกลางคันและลบไฟล์ค้างใน `SDCardManager` (`test_tc019`); รอเชื่อมการหยุดคิวใน Phase 3 |
| **TC-020** | การตรวจสอบไฟล์ด้วย `OutputValidator` | **Pass** | `test_tc020_output_validator_rejects_corrupt_non_aac_and_missing_title_files` |
| **TC-021** | Automated Regression Testing Pipeline | **Pass** | `test_tc021_phase2_core_pipeline_end_to_end_regression` (และชุดทดสอบ `pytest` ทั้งหมด) |
| **TC-022** | ไม่พบปกอัลบั้ม (สวิตซ์ค่าเริ่มต้น `require_cover=False`) | **Pass** | `test_tc022_missing_cover_with_default_switch_passes_with_warning` |
| **TC-023** | ไม่พบปกอัลบั้ม (บังคับต้องมีปก `require_cover=True`) | **Pass** | `test_tc023_missing_cover_with_require_cover_true_fails_validation` |
| **TC-024** | การเลือกสตรีมเสียง (Remux AAC vs Encode AAC-LC) | **Not Run** | รอพัฒนา `DownloadSourceAdapter` และ `AudioProcessingService` ใน Phase 3 |
| **TC-025** | ชื่อลงท้ายด้วยจุด/ช่องว่าง, อักขระควบคุม และชื่อสงวน | **Pass** | `test_tc025_trailing_dots_spaces_control_chars_and_reserved_names_on_windows` |
| **TC-026** | เกณฑ์ยอมรับผลค้นหา iTunes/MusicBrainz (`DEC-035`) | **Partial Pass** | ผ่านโครงสร้าง `MetadataMatcherProtocol` ด้วย Fake Matcher (`test_tc026`); อัลกอริทึมเทียบชื่อจริงยังเป็น `TBA-026` |
| **TC-027** | เส้นทางยาวเกินเพดาน Windows `MAX_PATH` (`> 259` อักขระ) | **Pass** | `test_tc027_path_exceeding_windows_max_path_raises_err_path_too_long` |
| **TC-028** | Overwrite แล้วการ์ดหลุดกลางคัน (`DEC-040`) | **Pass** | `test_tc028_overwrite_card_disconnected_mid_copy_preserves_original_file` |
| **TC-029** | Personal Use Disclaimer | **Partial Pass** | ผ่านส่วนบันทึกและอ่านค่า `disclaimer_accepted` ใน `config.json` (`test_tc029`); รอส่วน Modal UI ใน Phase 4 |
| **TC-030** | การจัดการ `config.json` และ `history.json` | **Pass** | `test_tc030a_config_and_history_normal_read_write`, `test_tc030b_corrupted_config_and_history_recovery` |
| **TC-031** | การอัปเดตโมดูล `yt-dlp.exe` | **Not Run** | รอพัฒนา `DownloadSourceAdapter.update_ytdlp()` ใน Phase 3 |
| **TC-032** | ความเป็นส่วนตัวของ `cookies.txt` ใน Logging | **Pass** | `test_tc032_cookies_and_tokens_never_appear_in_logs_or_structured_error` |
| **TC-033** | ขอบเขต `Apply to all` (`DEC-044`) | **Not Run** | รอพัฒนา `DownloadQueueManager` ใน Phase 3 |

---

## 5. รายการค่า `[Proposal]` และรายการ `TBA` ที่คงสถานะไว้

### 5.1 ค่าที่เป็น `[Proposal]` ในโค้ด (แยกเป็นค่าคงที่จุดเดียวเพื่อให้ง่ายต่อการเปลี่ยน)
1. **`CONFIG_KEY_REQUIRE_ALBUM_ART = "require_album_art"`** ใน [`src/pladaz/services/config_store.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/src/pladaz/services/config_store.py#L17)
2. **`DEFAULT_LOG_MAX_BYTES = 5 * 1024 * 1024`** (5 MB) และ **`DEFAULT_LOG_BACKUP_COUNT = 3`** ใน [`src/pladaz/services/logger.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/src/pladaz/services/logger.py#L13-L14)
3. **`OVERWRITE_TEMP_SUFFIX = ".pladaz-tmp"`** ใน [`src/pladaz/services/sd_card_manager.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/src/pladaz/services/sd_card_manager.py#L26)

### 5.2 หัวข้อที่ยังคงสถานะ `TBA` อย่างเคร่งครัด (ไม่ได้คาดเดาหรือเติมค่าเอง)
1. **`TBA-023`:** เกณฑ์ตัวเลขด้านประสิทธิภาพและขนาดไฟล์สูงสุดที่ยอมรับได้
2. **`TBA-026`:** รายละเอียดวิธีเทียบชื่อเพลงและศิลปินกับผลค้นหา iTunes/MusicBrainz (ตัวพิมพ์เล็ก-ใหญ่, การตัด `(Official Video)` / `feat.`, และสตริง `User-Agent`) — ต้องกำหนดก่อนเขียน `services/metadata_matcher.py` ใน Phase 3
3. **`TBA-027`:** ค่า Bitrate สำหรับกรณี Fallback Encode เป็น AAC-LC ด้วย FFmpeg — ต้องกำหนดก่อนหรือระหว่างพัฒนา `services/audio_processor.py` ใน Phase 3

