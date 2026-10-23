# PLADAZ — บันทึกความคืบหน้าโครงการ (Project Progress Log)

> **เอกสารติดตามความคืบหน้าและหลักฐานการพัฒนา (Project Progress & Verification Log)**
>
> **ชื่อโครงการ:** PLADAZ  
> **อัปเดตล่าสุด:** 2026-10-24  
> **เอกสารอ้างอิงหลัก:** [`Doc/IMPLEMENT_PLAN.md`](file:///e:/Doc/Code/randombullshit/PLADAZV2/Doc/IMPLEMENT_PLAN.md) (v2.5) และ [`Doc/SYSTEM_DESIGN.md`](file:///e:/Doc/Code/randombullshit/PLADAZV2/Doc/SYSTEM_DESIGN.md) (v2.3)  
> **ระยะปัจจุบัน:** เสร็จสิ้น **Phase 0–4** และส่วนงานอัตโนมัติ/เอกสารของ **Phase 5 (QA & Release Readiness)** — รอผลการทดสอบบนฮาร์ดแวร์จริง (`TC-015`, Micro SD Card จริง, Clean Windows) และข้อความ Disclaimer จากเจ้าของโครงการ

---

## 1. ภาพรวมสถานะรายระยะ (Phase Overview)

| ระยะ (Phase) | ชื่อระยะ | สถานะ | สรุปผลงานหลัก |
|---|---|---|---|
| **Phase 0** | ยืนยันข้อกำหนด (Requirements & Decisions) | **เสร็จสิ้น** | ยืนยัน `IR-001`–`IR-021`, บันทึกการตัดสินใจ `DEC-001`–`DEC-044`, แยกเอกสาร UI Design (`DEC-028`), และคงสถานะ `TBA` เฉพาะ `TBA-023`, `TBA-026`, `TBA-027` |
| **Phase 1** | ออกแบบระบบเชิงเทคนิค (System Design) | **เสร็จสิ้น** | จัดทำ [`Doc/SYSTEM_DESIGN.md`](file:///e:/Doc/Code/randombullshit/PLADAZV2/Doc/SYSTEM_DESIGN.md) ครอบคลุมสถาปัตยกรรม 3 ชั้น (`ui`/`bridge`/`services`+`domain`), Data Models, Module Contracts, State Machine, Error Codes และ Traceability Matrix |
| **Phase 2** | สร้างแกนระบบ (Core Backend & Unit/Integration Tests) | **เสร็จสิ้น** | พัฒนาแพ็กเกจ `pladaz` (`domain/` + 6 โมดูลแกนหลักใน `services/`) พร้อมสภาพแวดล้อม `venv` และชุดทดสอบ `pytest` 34 รายการ |
| **Phase 3** | เชื่อมต่อกระบวนการเพลง (Download, Audio & Queue) | **เสร็จสิ้น** | พัฒนา `DownloadSourceAdapter` (`yt-dlp.exe`), `AudioProcessingService` (`ffmpeg.exe`), `HttpExternalMetadataFetcher` + `TemporaryExactMetadataMatcher`, `DownloadQueueManager`, `EventDispatcher`, `dto.py`, และ `BridgeAPI` |
| **Phase 4** | พัฒนา Frontend, App Shell และ Packaging | **เสร็จสิ้น** | พัฒนา `paths.py`, `main.py` (`pywebview` `1280×820`), `ui/js/bridge.js`, `ui/js/app.js`, `ui/index.html` ครบ 19 บอร์ดที่อนุมัติ (`01`–`11`, `13`–`20`), แก้ไขข้อบกพร่องจากการตรวจสอบ QA ทั้งหมด (Conflict Prompt recovery, การแจ้งเตือนคำสั่งล้มเหลว, การตรวจพาธใน Backend, การอัปเดต DOM เฉพาะแถว, สรุปผลเฉพาะรอบปัจจุบัน และความตรงปกตาม Design Direction), และบิลด์ `dist/PLADAZ/PLADAZ.exe` โหมด `--onedir` |
| **Phase 5** | ตรวจสอบและเตรียมใช้งาน (QA & Release) | **ดำเนินการส่วนอัตโนมัติเสร็จสิ้น / รอผลฮาร์ดแวร์จริงจากผู้ใช้** | ติดตั้งสคริปต์ Regression [`scripts/run_tests.ps1`](file:///e:/Doc/Code/randombullshit/PLADAZV2/scripts/run_tests.ps1) และสคริปต์ตรวจการ์ด [`scripts/verify_sd_card.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/scripts/verify_sd_card.py), เพิ่มชุดทดสอบ E2E และ Frontend JS รวม **59 รายการ (รันออฟไลน์ผ่าน 58/58 รายการ, ข้ามชุดทดสอบเน็ตจริง 1 รายการที่รอ URL)**, และจัดทำ `USER_GUIDE.md`, `KNOWN_LIMITATIONS.md`, `TEST_REPORT.md`, `RELEASE_READINESS_REPORT.md` |

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
  - การควบคุมคิวแบบแมนนวล (`Start` / `Cancel` → `Failed` รหัส `ERR_TASK_CANCELLED` / `Resume`) (`DEC-042`, `TC-016`)
  - การตรวจจับเส้นทางยาวเกินเพดาน Windows `MAX_PATH` (`> 259` อักขระ → `ERR_PATH_TOO_LONG`) (`DEC-043`, `TC-027`)
  - ขอบเขตของ `Apply to all in this album` และ `Apply to all in queue` (`DEC-044`, `TC-033`)

### 2.2 Phase 1 — การออกแบบระบบเชิงเทคนิค
- จัดทำเอกสาร [`Doc/SYSTEM_DESIGN.md`](file:///e:/Doc/Code/randombullshit/PLADAZV2/Doc/SYSTEM_DESIGN.md) กำหนดโครงสร้างโปรเจกต์, Data Classes, Enums, Protocols, Sequence Diagram, State Machine, ตารางรหัสข้อผิดพลาด (`ErrorCode`) และ Traceability Matrix เชื่อมโยง `IR` ↔ `DEC/TBA` ↔ โมดูล ↔ `TC-001` ถึง `TC-033`

---

## 3. บันทึกสิ่งที่ดำเนินการเสร็จแล้วใน Phase 2 — สร้างแกนระบบ

- **สภาพแวดล้อมเสมือน (`venv`):** Python `3.13.5` บน Windows 11 (`win32`)
- **แพ็กเกจที่ติดตั้ง:** `pladaz==1.0.0`, `mutagen==1.48.1`, `Pillow==13.0.0`, `psutil==7.2.2`, `pywebview==6.2.1`, `pyinstaller==6.22.3`, `pytest==9.1.1`
- **โมดูลแกนหลัก:**
  - `src/pladaz/domain/` (`enums.py`, `models.py`, `errors.py`, `interfaces.py`)
  - `src/pladaz/services/` (`logger.py`, `config_store.py`, `folder_organizer.py`, `metadata_service.py`, `sd_card_manager.py`, `output_validator.py`)

---

## 4. บันทึกสิ่งที่ดำเนินการเสร็จแล้วใน Phase 3 — เชื่อมต่อกระบวนการเพลง

- พัฒนา [`src/pladaz/services/source_adapter.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/src/pladaz/services/source_adapter.py) (`DownloadSourceAdapter`), [`src/pladaz/services/audio_processor.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/src/pladaz/services/audio_processor.py) (`AudioProcessingService`), [`src/pladaz/services/metadata_matcher.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/src/pladaz/services/metadata_matcher.py) (`TemporaryExactMetadataMatcher` & `HttpExternalMetadataFetcher`), [`src/pladaz/services/queue_manager.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/src/pladaz/services/queue_manager.py) (`DownloadQueueManager`), และชั้นเชื่อมต่อ [`src/pladaz/bridge/`](file:///e:/Doc/Code/randombullshit/PLADAZV2/src/pladaz/bridge/api.py) (`dto.py`, `events.py`, `api.py`)

---

## 5. บันทึกสิ่งที่ดำเนินการเสร็จแล้วใน Phase 4 และงานแก้ไขจากการตรวจสอบ QA ใน Phase 5

### 5.1 โมดูล Frontend, App Shell และการแก้ไขจุดบกพร่องจากการตรวจประเมิน
1. **การป้องกัน Conflict Prompt ค้างถาวร (`queue_manager.py`, `api.py`, `ui/js/app.js`):**
   - `DownloadQueueManager` เก็บสถานะ `_pending_conflict_payloads` และส่งออกผ่าน `get_pending_conflict()` ใน `BridgeAPI.get_initial_state()`
   - `submitConflictChoice` ใน `ui/js/app.js` รอผล `resolveConflict` ให้สำเร็จ (`res.success === true`) ก่อนจึงจะปิด Modal และล้าง `pendingConflict` หากล้มเหลวจะคงหน้าต่างไว้และแสดงแบนเนอร์แจ้งข้อผิดพลาด รวมถึงกู้คืนหน้าต่าง Conflict ได้เมื่อเปิดแอปใหม่หรือกดปุ่ม `OPEN PROMPT`
2. **การตรวจสอบผลลัพธ์ของคำสั่งทั้งหมดและการให้ Backend ถือสถานะคิวอย่างเดียว (`api.py`, `events.py`, `ui/js/app.js`):**
   - ทุกคำสั่งใน `ui/js/app.js` ตรวจสอบ `res.success` และเรียก `reportCommandError()` เพื่อแสดงแบนเนอร์ข้อผิดพลาดให้ผู้ใช้เห็นเมื่อคำสั่งล้มเหลว
   - UI ไม่ตั้งค่า `queueHalted` ล่วงหน้าเองอีกต่อไป แต่รับค่า `queue_running` และ `queue_halted` จากการตอบกลับของ Backend และ Event (`queue:updated`, `task:status_changed`) เท่านั้น
3. **การป้องกันการส่งพาธจากหน้าเว็บและการตรวจไดรฟ์ใน Backend เท่านั้น (`bridge.js`, `api.py`, `app.js`):**
   - `browse_destination_folder()`, `select_cookies_file()`, และ `locate_ytdlp_file()` ไม่รับพารามิเตอร์พาธจากหน้าเว็บ (เปิดเฉพาะ Native File/Folder Dialog ของ Backend)
   - เพิ่มเมธอด `select_detected_drive(drive_root)` สำหรับปุ่ม `USE THIS CARD` โดยตรวจใน Backend เท่านั้นว่าอยู่ในรายการ `list_removable_drives()` และเขียนได้จริง
   - เพิ่มเมธอด `clear_cookies_file()` แยกชัดเจนสำหรับปุ่ม `REMOVE` แทนการส่งสตริงว่าง `""`
4. **การอัปเดต DOM เฉพาะแถวและการนับสรุปผลเฉพาะรอบปัจจุบัน (`ui/js/app.js`):**
   - เหตุการณ์ `task:progress` เรียก `updateTaskRowProgress(task)` เพื่ออัปเดตเฉพาะแถว `[data-task-row-id]` โดยไม่เขียนทับ `innerHTML` ทั้งรายการคิว
   - บันทึก `state.activeRunTaskIds` เพื่อให้นับสรุปผลเมื่องานในคิวจบเฉพาะเพลงที่รันในรอบปัจจุบัน ไม่นับรวมงานเก่าที่ค้างจากรอบก่อนหน้า
5. **ความถูกต้องของข้อมูลในหน้า Track Detail และการโหลดภาพปกซ้ำ (`ui/js/app.js`, `ui/index.html`):**
   - ไม่เดาสถานะ Validator เป็น `PASS` เมื่อ `task.validation` เป็น `null` (แสดง `NO VALIDATION DATA` / `NO DATA` ตามจริง)
   - ป้าย `covr` แสดงข้อความตามค่า `task.has_cover` จริง และ `ensureCoverLoaded()` รองรับการดึงภาพปกซ้ำหากการเรียกครั้งแรกเกิดขึ้นก่อนที่ปกจะประมวลผลเสร็จ
6. **ความตรงตาม Design Direction (`ui_src/input.css`, `ui/index.html`, `ui/js/app.js`, `Doc/PLADAZ — Design Direction & Handoff.md`):**
   - ปรับขนาดตัวอักษรขั้นต่ำทั่วทั้ง UI ให้ไม่ต่ำกว่า `12px` (`text-xs`), ใช้แถบความคืบหน้าแบบ 10 ช่อง (10-segment bar), ป้าย `✕ Failed` พื้นสีกรมท่าเข้ม `#2B2540` ตัวหนังสือขาว, และกล่องคำพูด `.speech-bubble` พร้อมหางสามเหลี่ยมและไอคอนพิกเซล 16×16 ในส่วน Now Processing
   - อัปเดตเอกสาร `Doc/PLADAZ — Design Direction & Handoff.md` ให้มีตารางครบทั้ง 20 บอร์ดและสอดคล้องกับ `DEC-019` (`Keep Both` เติม ` (1)`)
7. **การปรับปรุง `LICENSE-THIRD-PARTY.txt` และการตัด `ffprobe.exe` ออก:**
   - เพิ่มรายละเอียดสัญญาอนุญาต `GPLv2+` ของ `mutagen` และ `GPLv3` ของ `FFmpeg (gyan.dev release_full build)` พร้อมคำอธิบายเงื่อนไขกรณีแจกจ่ายต่อ
   - ตัด `ffprobe.exe` ออกเพื่อประหยัดพื้นที่ 227 MB เนื่องจากแอปใช้ pure-Python `mutagen.mp4.MP4` และ `AudioValidatorService` ในการตรวจสอบ atoms และ codec โดยตรง
8. **การปรับปรุงสถาปัตยกรรม Binary, การแก้ปัญหาภาพปก และการบิลด์เวอร์ชันล่าสุด:**
   - ย้าย `yt-dlp.exe` เข้าไปอยู่ใน `_internal/bin/yt-dlp.exe` ร่วมกับ `ffmpeg.exe` โดย `paths.py` รองรับ fallback หาข้าง `.exe` เพื่อความสะอาดของ root folder ในโหมด `--onedir`
   - ปรับแต่ง `DownloadSourceAdapter.update_ytdlp()` ให้ทำการ in-place update ตรงตำแหน่งติดตั้ง binary ผ่าน atomic swap (`os.replace`)
   - ต่อสาย `TemporaryExactMetadataMatcher` และ `HttpExternalMetadataFetcher` เข้ากับ `MetadataAlbumArtService` ใน `main.py` พร้อมเพิ่ม HTTP fallback ดาวน์โหลดภาพปกจาก YouTube stream `thumbnails` ทำให้ M4A มีภาพปก 800×800 JPEG ฝังใน atom `covr` เสมอ
   - สร้างไฟล์ `.gitignore` เพื่อป้องกันการ commit binaries ขนาดใหญ่ (`*.exe`, `dist/`, `build/`) เข้า Git โดยอาศัย GitHub Releases ในการแจกจ่าย
   - บิลด์ `dist\PLADAZ\PLADAZ.exe` ล่าสุดด้วย PyInstaller (จาก commit `ba20fd7`, 2026-10-24, smoke test exit code `0`): ขนาด `5,900,807` ไบต์, SHA-256: `8FA05A7DF0FB8A825863B5A74D95543D12BD37E9606053F70EB66E80CC9F5323` (รายละเอียดและแฮชของ `yt-dlp.exe` / `ffmpeg.exe` ใน `TEST_REPORT.md` หัวข้อ 5.4)

---

## 6. หลักฐานการทดสอบอัตโนมัติ (`pytest`) และสถานะ Test Cases ทั้งหมด

### 6.1 สรุปผลการรัน `pytest` ล่าสุด (Phase 2 + Phase 3 + Phase 4 + Phase 5)
- **คำสั่งรันชุดทดสอบออฟไลน์ทั้งหมด:** `.\venv\Scripts\python.exe -m pytest -v -m "not network"`
- **จำนวนการทดสอบทั้งหมดที่รวบรวมได้:** **59 รายการ** (ใน 14 ไฟล์ทดสอบ)
- **ผลลัพธ์:** **`58 passed, 1 deselected in 5.86s`** (`0 failed`)
  - **Unit Tests (`-m "unit"`):** **36 passed**
  - **Integration Tests (`-m "integration and not e2e"`):** **21 passed**
  - **End-to-End Tests (`-m "e2e"`):** **1 passed** (ออฟไลน์), **1 skipped/deselected** (ออนไลน์ รอ `PLADAZ_TEST_URLS`)

| ไฟล์ทดสอบ | จำนวน Test Functions | ผลลัพธ์ | ขอบเขตที่ทดสอบ |
|---|:---:|---|---|
| [`tests/unit/test_logger.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/tests/unit/test_logger.py) | 3 | **3 Passed** | `TC-017`, `TC-032`, และการหมุนไฟล์ Log (`RotatingFileHandler`) |
| [`tests/unit/test_config_store.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/tests/unit/test_config_store.py) | 3 | **3 Passed** | `TC-029` (ส่วนบันทึก config), `TC-030` (อ่าน-เขียนปกติและกู้คืนไฟล์ JSON เสีย) |
| [`tests/unit/test_folder_organizer.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/tests/unit/test_folder_organizer.py) | 8 | **8 Passed** | `TC-002`, `TC-003`, `TC-011` (ส่วนโฟลเดอร์), `TC-012`, `TC-013` (ส่วนคำนวณชื่อซ้ำ), `TC-025`, `TC-026` (ส่วนโฟลเดอร์), `TC-027` |
| [`tests/unit/test_metadata_rules.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/tests/unit/test_metadata_rules.py) | 7 | **7 Passed** | `TC-004`, `TC-005`, `TC-006`, `TC-007`, `TC-011` (ส่วนแท็ก), `TC-026` (ผ่าน Fake Matcher), และกรณี API เสริมล้มเหลว |
| [`tests/unit/test_output_validator.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/tests/unit/test_output_validator.py) | 5 | **5 Passed** | `TC-014`, `TC-020`, `TC-022`, `TC-023`, และกรณีข้อมูลภาพปกใน `covr` เสียหาย |
| [`tests/unit/test_source_adapter.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/tests/unit/test_source_adapter.py) | 5 | **5 Passed** | การตรวจ URL (`ERR_SOURCE_INVALID_URL`), การแปลง JSON ของ Single/Playlist, `plan_stream` (`DEC-033`), การยกเลิก `download_stream`, และ `TC-031` (`update_ytdlp`) |
| [`tests/unit/test_conflict_resolution.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/tests/unit/test_conflict_resolution.py) | 3 | **3 Passed** | `TC-013` (Overwrite / Skip / Keep Both ก่อนดาวน์โหลดเสียง), `TC-033(a)`, และ `TC-033(b)` |
| [`tests/test_frontend_js.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/tests/test_frontend_js.py) | 2 | **2 Passed** | ทดสอบพฤติกรรม `ui/js/bridge.js` และ `ui/js/app.js` ด้วย Node.js VM harness และตรวจสอบกฎ Design Direction ใน HTML/CSS/JS |
| [`tests/integration/test_sd_card_manager.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/tests/integration/test_sd_card_manager.py) | 6 | **6 Passed** | `TC-008` (ส่วนจำลอง), `TC-009`, `TC-010`, `TC-019` (การ์ดหลุดขณะคัดลอก), `TC-028` (Overwrite แล้วการ์ดหลุด), และกรณี Verify ขนาดไฟล์ไม่ตรง |
| [`tests/integration/test_core_pipeline.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/tests/integration/test_core_pipeline.py) | 2 | **2 Passed** | `TC-021` (บูรณาการแกนระบบ) และการตรวจ AST ยืนยันว่า `domain/` ไม่ import ไลบรารีต้องห้าม |
| [`tests/integration/test_audio_pipeline.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/tests/integration/test_audio_pipeline.py) | 3 | **3 Passed** | `TC-024(a)` (`REMUX_AAC` ด้วย `ffmpeg.exe` จริง), `TC-024(b)` (`ENCODE_AAC_LC` ด้วย `ffmpeg.exe` จริง), และ `HttpExternalMetadataFetcher` |
| [`tests/integration/test_queue_worker.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/tests/integration/test_queue_worker.py) | 4 | **4 Passed** | `TC-018` (Sequential Queue transitions), `TC-016` (Cancel กลางทาง + ลบ Temp + Retry), `TC-019` (การ์ดหลุดกลางการดาวน์โหลด), และการผสาน `OutputValidator` + `BridgeAPI` |
| [`tests/test_phase4_bridge_and_shell.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/tests/test_phase4_bridge_and_shell.py) | 6 | **6 Passed** | `resolve_app_paths`, `create_app_context`, เมธอด `BridgeAPI` (รวม `select_detected_drive`, `clear_cookies_file`, `pending_conflict`), การยกเลิกงานและหยุดคิว (`DEC-049`), สัญญา Event Payload ครบทั้ง 6 Event, และการตรวจออฟไลน์ UI Bundle |
| [`tests/e2e/test_bridge_e2e.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/tests/e2e/test_bridge_e2e.py) | 2 | **1 Passed, 1 Skipped** | `test_bridge_e2e_full_queue_workflow_and_atom_verification` (ผ่านครบตั้งแต่วางลิงก์จนตรวจ MP4 Atoms บนปลายทาง) และ `test_bridge_e2e_live_network_download` (ข้ามเมื่อไม่กำหนด `PLADAZ_TEST_URLS`) |

### 6.2 ตารางสถานะ Test Cases (`TC-001` ถึง `TC-033`) — ใช้เฉพาะ 4 สถานะมาตรฐาน (`Pass`, `Fail`, `Blocked`, `Not Run`)

| TC ID | ชื่อการทดสอบ | สถานะปัจจุบัน | หลักฐาน / หมายเหตุ |
|---|---|:---:|---|
| **TC-001** | เปิดใช้งานบน Windows | **Blocked** | รัน `dist\PLADAZ\PLADAZ.exe --smoke-test` ผ่าน (`ExitCode=0`); แต่เกณฑ์ตัวเลขประสิทธิภาพ/ขนาดไฟล์ยังติด `TBA-023` และรอผลทดสอบบนเครื่อง Windows สะอาด |
| **TC-002** | สร้างเส้นทางโฟลเดอร์ (`Album Artist` / `Album`) | **Pass** | `test_tc002_build_target_path_with_album_artist_and_album` |
| **TC-003** | ไม่ใช้ `Track Artist` เป็นโฟลเดอร์หลัก | **Pass** | `test_tc003_folder_uses_album_artist_not_track_artist` |
| **TC-004** | รองรับ Metadata หลัก (`Title`, `Track Artist`, `Album`, `Album Artist`) | **Pass** | `test_tc004_core_metadata_tags_written_and_verified_with_uppercase_art_atom` |
| **TC-005** | รองรับลำดับแทร็กและแผ่น (`trkn`, `disk`) | **Pass** | `test_tc005_track_number_and_disc_number_atoms` |
| **TC-006** | รองรับ `Year` และ `Genre` (`©day`, `©gen`) | **Pass** | `test_tc006_year_and_genre_atoms` |
| **TC-007** | รองรับ `Album Art` (800×800 JPEG ใน `covr`) | **Pass** | `test_tc007_process_cover_800x800_jpeg_and_embed_in_covr_atom` |
| **TC-008** | เลือกปลายทางบนพื้นที่จัดเก็บข้อมูล | **Not Run** | ส่วนซอฟต์แวร์ (`test_tc008` และ `select_detected_drive`) ผ่านแล้ว; รอผลทดสอบกับการ์ด Micro SD จริงจากผู้ใช้ |
| **TC-009** | ปลายทางไม่พร้อมใช้งาน | **Pass** | `test_tc009_destination_disconnected_or_read_only_raises_error` คืน `ERR_SDCARD_DISCONNECTED` |
| **TC-010** | พื้นที่ไม่เพียงพอ | **Pass** | `test_tc010_insufficient_free_space_raises_error` คืน `ERR_SDCARD_INSUFFICIENT_SPACE` |
| **TC-011** | ไม่มี Metadata บางฟิลด์ | **Pass** | ผ่านทั้งส่วนแท็ก (`test_metadata_rules.py`) และส่วนโฟลเดอร์ `'Unknown Artist'` (`test_folder_organizer.py`) |
| **TC-012** | ชื่อโฟลเดอร์มีอักขระต้องห้าม | **Pass** | `test_tc012_windows_forbidden_characters_replaced_with_underscore` |
| **TC-013** | นโยบายจัดการไฟล์ซ้ำ (Overwrite / Skip / Keep Both ก่อนดาวน์โหลดเสียง) | **Pass** | `test_tc013_conflict_prompt_before_audio_download_overwrite_skip_and_keep_both` และ `test_frontend_js.py` |
| **TC-014** | ตรวจสอบไฟล์ผลลัพธ์ | **Pass** | `test_tc014_valid_aac_lc_m4a_with_metadata_and_cover_passes` |
| **TC-015** | อ่านไฟล์บนเครื่องเป้าหมาย (SNOWSKY ECHO DAP) | **Not Run** | ต้องทดสอบด้วยมือบนเครื่องเล่นจริงโดยผู้ใช้ตาม Checklist F |
| **TC-016** | การยกเลิก/ความล้มเหลวกลางทาง (`Cancel` → `ERR_TASK_CANCELLED`) | **Pass** | `test_tc016_cancel_mid_download_cleans_temp_and_sets_failed_err_task_cancelled` และ `test_frontend_js.py` |
| **TC-017** | การบันทึกข้อผิดพลาดลง Log | **Pass** | `test_tc017_error_logging_contains_required_diagnostic_fields` |
| **TC-018** | การทำงานของ Download Queue (`Queued` → `Downloading` → `Completed`/`Failed`) | **Pass** | `test_tc018_download_queue_sequential_state_transitions` และ `test_frontend_js.py` |
| **TC-019** | การตรวจจับการ์ดและการถอด Micro SD Card กลางคัน | **Not Run** | การทดสอบจำลองอัตโนมัติผ่านแล้ว; รอผลทดสอบดึงการ์ดจริงโดยผู้ใช้ตาม Checklist E |
| **TC-020** | การตรวจสอบไฟล์ด้วย `OutputValidator` | **Pass** | `test_tc020_output_validator_rejects_corrupt_non_aac_and_missing_title_files` |
| **TC-021** | Automated Regression Testing Pipeline | **Pass** | `scripts/run_tests.ps1` รันชุดทดสอบออฟไลน์ 58 รายการผ่านครบ และพิสูจน์การจับ Regression ได้จริง |
| **TC-022** | ไม่พบปกอัลบั้ม (สวิตซ์ค่าเริ่มต้น `require_cover=False`) | **Pass** | `test_tc022_missing_cover_with_default_switch_passes_with_warning` |
| **TC-023** | ไม่พบปกอัลบั้ม (บังคับต้องมีปก `require_cover=True`) | **Pass** | `test_tc023_missing_cover_with_require_cover_true_fails_validation` |
| **TC-024** | การเลือกสตรีมเสียง (`REMUX_AAC` vs `ENCODE_AAC_LC`) | **Pass** | `test_tc024a_stream_with_aac_lc_uses_remux` และ `test_tc024b_stream_without_aac_encodes_to_aac_lc` (รันด้วย `ffmpeg.exe` จริงตาม Plan 9.2) |
| **TC-025** | ชื่อลงท้ายด้วยจุด/ช่องว่าง, อักขระควบคุม และชื่อสงวน | **Pass** | `test_tc025_trailing_dots_spaces_control_chars_and_reserved_names_on_windows` |
| **TC-026** | เกณฑ์ยอมรับผลค้นหา iTunes/MusicBrainz (`DEC-035`) | **Blocked** | โครงสร้าง `TemporaryExactMetadataMatcher` ทำงานได้ถูกต้อง แต่อัลกอริทึมเทียบชื่อสุดท้ายและ `User-Agent` ของ MusicBrainz ยังติด `TBA-026` |
| **TC-027** | เส้นทางยาวเกินเพดาน Windows `MAX_PATH` (`> 259` อักขระ) | **Pass** | `test_tc027_path_exceeding_windows_max_path_raises_err_path_too_long` |
| **TC-028** | Overwrite แล้วการ์ดหลุดกลางคัน (`DEC-040`) | **Not Run** | การทดสอบจำลองอัตโนมัติผ่านแล้ว; รอผลทดสอบกับการ์ดจริงโดยผู้ใช้ตาม Checklist E |
| **TC-029** | Personal Use Disclaimer | **Blocked** | กลไกบันทึก `disclaimer_accepted` ผ่านการทดสอบอัตโนมัติแล้ว แต่ข้อความจริงในบอร์ด 04 ยังเป็น Placeholder รอเจ้าของโครงการระบุ (`TBA-023`) |
| **TC-030** | การจัดการ `config.json` และ `history.json` | **Pass** | `test_tc030a_config_and_history_normal_read_write` และ `test_tc030b_corrupted_config_and_history_recovery` |
| **TC-031** | การอัปเดตโมดูล `yt-dlp.exe` | **Pass** | `test_tc031_update_ytdlp_success_and_failure_rollback` |
| **TC-032** | ความเป็นส่วนตัวของ `cookies.txt` ใน Logging | **Pass** | `test_tc032_cookies_and_tokens_never_appear_in_logs_or_structured_error` |
| **TC-033** | ขอบเขต `Apply to all` (`DEC-044`) | **Pass** | `test_tc033a` และ `test_tc033b` |

---

## 7. รายการค่า `[Proposal]` และรายการ `TBA` ที่คงสถานะไว้

### 7.1 ค่าที่เป็น `[Proposal]` หรือค่าตั้งต้นที่แยกไว้เป็นค่าคงที่จุดเดียว
1. **`CONFIG_KEY_REQUIRE_ALBUM_ART = "require_album_art"`** ใน [`src/pladaz/services/config_store.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/src/pladaz/services/config_store.py#L17)
2. **`DEFAULT_LOG_MAX_BYTES = 5 * 1024 * 1024`** (5 MB) และ **`DEFAULT_LOG_BACKUP_COUNT = 3`** ใน [`src/pladaz/services/logger.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/src/pladaz/services/logger.py#L13-L14)
3. **`OVERWRITE_TEMP_SUFFIX = ".pladaz-tmp"`** ใน [`src/pladaz/services/sd_card_manager.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/src/pladaz/services/sd_card_manager.py#L26)
4. **`DEFAULT_SD_POLL_INTERVAL_SEC = 2.0`** (2.0 วินาที) ใน [`src/pladaz/services/queue_manager.py`](file:///e:/Doc/Code/randombullshit/PLADAZV2/src/pladaz/services/queue_manager.py#L39)

### 7.2 หัวข้อที่ยังคงสถานะ `TBA` อย่างเคร่งครัด (ไม่ได้คาดเดาหรือเติมค่าเอง)
1. **`TBA-023`:** เกณฑ์ตัวเลขด้านประสิทธิภาพและขนาดไฟล์สูงสุดที่ยอมรับได้ รวมถึงข้อความจริงของ Personal Use Disclaimer
2. **`TBA-026`:** รายละเอียดวิธีเทียบชื่อเพลงและศิลปินกับผลค้นหา iTunes/MusicBrainz (ปัจจุบันใช้ [`TemporaryExactMetadataMatcher`](file:///e:/Doc/Code/randombullshit/PLADAZV2/src/pladaz/services/metadata_matcher.py#L26-L46) ที่ติดป้ายชั่วคราว) และสตริง `User-Agent` สำหรับ MusicBrainz (รับจากการตั้งค่า ไม่แต่งข้อมูลติดต่อผู้พัฒนาเอง)
3. **`TBA-027`:** ค่า Bitrate สำหรับกรณี Fallback Encode เป็น AAC-LC ด้วย FFmpeg (ปัจจุบันพารามิเตอร์ `fallback_bitrate` ใน [`AudioProcessingService`](file:///e:/Doc/Code/randombullshit/PLADAZV2/src/pladaz/services/audio_processor.py#L46) มีค่าเริ่มต้นเป็น `None` ไม่ส่ง `-b:a`)
