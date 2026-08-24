

-- ---------------------------------------------------------
-- Reset and seed document table for local testing
-- 실행 순서: 스키마 생성 후 한 번만 실행하세요.
-- 예: mysql -u <사용자> -p < RAG/sql/rag_document.sql
-- ---------------------------------------------------------

SET foreign_key_checks = 0;
TRUNCATE TABLE `document`;
SET foreign_key_checks = 1;

-- 공통 PDF 문서 데이터 (숫자로 시작하는 파일 - common_ 접두사로 구분)
INSERT INTO `document` (`original_file_name`, `stored_file_name`, `file_path`, `is_loaded`, `loaded_at`) VALUES ('1.남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률(법률).pdf', 'common_1.남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률(법률).pdf', 'res/pdf/1.남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률(법률).pdf', 0, null);
INSERT INTO `document` (`original_file_name`, `stored_file_name`, `file_path`, `is_loaded`, `loaded_at`) VALUES ('1.남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률(시행규칙).pdf', 'common_1.남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률(시행규칙).pdf', 'res/pdf/1.남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률(시행규칙).pdf', 0, null);
INSERT INTO `document` (`original_file_name`, `stored_file_name`, `file_path`, `is_loaded`, `loaded_at`) VALUES ('1.남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률(시행령).pdf', 'common_1.남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률(시행령).pdf', 'res/pdf/1.남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률(시행령).pdf', 0, null);
INSERT INTO `document` (`original_file_name`, `stored_file_name`, `file_path`, `is_loaded`, `loaded_at`) VALUES ('2.공공기관의 운영에 관한 법률(법률).pdf', 'common_2.공공기관의 운영에 관한 법률(법률).pdf', 'res/pdf/2.공공기관의 운영에 관한 법률(법률).pdf', 0, null);
INSERT INTO `document` (`original_file_name`, `stored_file_name`, `file_path`, `is_loaded`, `loaded_at`) VALUES ('2.공공기관의 운영에 관한 법률(시행령).pdf', 'common_2.공공기관의 운영에 관한 법률(시행령).pdf', 'res/pdf/2.공공기관의 운영에 관한 법률(시행령).pdf', 0, null);
INSERT INTO `document` (`original_file_name`, `stored_file_name`, `file_path`, `is_loaded`, `loaded_at`) VALUES ('3.교육공무원법(법률).pdf', 'common_3.교육공무원법(법률).pdf', 'res/pdf/3.교육공무원법(법률).pdf', 0, null);
INSERT INTO `document` (`original_file_name`, `stored_file_name`, `file_path`, `is_loaded`, `loaded_at`) VALUES ('4.교육공무원임용령(시행령).pdf', 'common_4.교육공무원임용령(시행령).pdf', 'res/pdf/4.교육공무원임용령(시행령).pdf', 0, null);
INSERT INTO `document` (`original_file_name`, `stored_file_name`, `file_path`, `is_loaded`, `loaded_at`) VALUES ('5.근로기준법(법률).pdf', 'common_5.근로기준법(법률).pdf', 'res/pdf/5.근로기준법(법률).pdf', 0, null);
INSERT INTO `document` (`original_file_name`, `stored_file_name`, `file_path`, `is_loaded`, `loaded_at`) VALUES ('5.근로기준법(시행규칙).pdf', 'common_5.근로기준법(시행규칙).pdf', 'res/pdf/5.근로기준법(시행규칙).pdf', 0, null);
INSERT INTO `document` (`original_file_name`, `stored_file_name`, `file_path`, `is_loaded`, `loaded_at`) VALUES ('5.근로기준법(시행령).pdf', 'common_5.근로기준법(시행령).pdf', 'res/pdf/5.근로기준법(시행령).pdf', 0, null);
INSERT INTO `document` (`original_file_name`, `stored_file_name`, `file_path`, `is_loaded`, `loaded_at`) VALUES ('6.기간제 및 단시간근로자 보호 등에 관한 법률(법률).pdf', 'common_6.기간제 및 단시간근로자 보호 등에 관한 법률(법률).pdf', 'res/pdf/6.기간제 및 단시간근로자 보호 등에 관한 법률(법률).pdf', 0, NULL);
INSERT INTO `document` (`original_file_name`, `stored_file_name`, `file_path`, `is_loaded`, `loaded_at`) VALUES ('6.기간제 및 단시간근로자 보호 등에 관한 법률(시행규칙).pdf', 'common_6.기간제 및 단시간근로자 보호 등에 관한 법률(시행규칙).pdf', 'res/pdf/6.기간제 및 단시간근로자 보호 등에 관한 법률(시행규칙).pdf', 0, NULL);
INSERT INTO `document` (`original_file_name`, `stored_file_name`, `file_path`, `is_loaded`, `loaded_at`) VALUES ('6.기간제 및 단시간근로자 보호 등에 관한 법률(시행령).pdf', 'common_6.기간제 및 단시간근로자 보호 등에 관한 법률(시행령).pdf', 'res/pdf/6.기간제 및 단시간근로자 보호 등에 관한 법률(시행령).pdf', 0, NULL);

-- 일반 PDF 문서 데이터 (숫자로 시작하지 않는 파일)
INSERT INTO `document` (`original_file_name`, `stored_file_name`, `file_path`, `is_loaded`, `loaded_at`) VALUES ('계약직직원임용지침.pdf', 'doc_계약직직원임용지침.pdf', 'res/pdf/계약직직원임용지침.pdf', 0, null);
INSERT INTO `document` (`original_file_name`, `stored_file_name`, `file_path`, `is_loaded`, `loaded_at`) VALUES ('공무직 직원 인사 및 보수에 관한 규칙.pdf', 'doc_공무직 직원 인사 및 보수에 관한 규칙.pdf', 'res/pdf/공무직 직원 인사 및 보수에 관한 규칙.pdf', 0, null);
INSERT INTO `document` (`original_file_name`, `stored_file_name`, `file_path`, `is_loaded`, `loaded_at`) VALUES ('교직원 음주운전 비위행위 확인에 관한 지침.pdf', 'doc_교직원 음주운전 비위행위 확인에 관한 지침.pdf', 'res/pdf/교직원 음주운전 비위행위 확인에 관한 지침.pdf', 0, null);
INSERT INTO `document` (`original_file_name`, `stored_file_name`, `file_path`, `is_loaded`, `loaded_at`) VALUES ('교직원특수병치료비지원지침.pdf', 'doc_교직원특수병치료비지원지침.pdf', 'res/pdf/교직원특수병치료비지원지침.pdf', 0, null);
INSERT INTO `document` (`original_file_name`, `stored_file_name`, `file_path`, `is_loaded`, `loaded_at`) VALUES ('국외여행에관한규칙.pdf', 'doc_국외여행에관한규칙.pdf', 'res/pdf/국외여행에관한규칙.pdf', 0, null);
INSERT INTO `document` (`original_file_name`, `stored_file_name`, `file_path`, `is_loaded`, `loaded_at`) VALUES ('별정직직원인사관리지침.pdf', 'doc_별정직직원인사관리지침.pdf', 'res/pdf/별정직직원인사관리지침.pdf', 0, null);
INSERT INTO `document` (`original_file_name`, `stored_file_name`, `file_path`, `is_loaded`, `loaded_at`) VALUES ('복무규정.pdf', 'doc_복무규정.pdf', 'res/pdf/복무규정.pdf', 0, null);
INSERT INTO `document` (`original_file_name`, `stored_file_name`, `file_path`, `is_loaded`, `loaded_at`) VALUES ('시간선택제 직원에 관한 규칙.pdf', 'doc_시간선택제 직원에 관한 규칙.pdf', 'res/pdf/시간선택제 직원에 관한 규칙.pdf', 0, null);
INSERT INTO `document` (`original_file_name`, `stored_file_name`, `file_path`, `is_loaded`, `loaded_at`) VALUES ('유연근무제 운영지침 .pdf', 'doc_유연근무제 운영지침 .pdf', 'res/pdf/유연근무제 운영지침 .pdf', 0, null);
INSERT INTO `document` (`original_file_name`, `stored_file_name`, `file_path`, `is_loaded`, `loaded_at`) VALUES ('직원승진시험시행 지침.pdf', 'doc_직원승진시험시행 지침.pdf', 'res/pdf/직원승진시험시행 지침.pdf', 0, null);
INSERT INTO `document` (`original_file_name`, `stored_file_name`, `file_path`, `is_loaded`, `loaded_at`) VALUES ('직원인사규정 시행규칙.pdf', 'doc_직원인사규정 시행규칙.pdf', 'res/pdf/직원인사규정 시행규칙.pdf', 0, null);
INSERT INTO `document` (`original_file_name`, `stored_file_name`, `file_path`, `is_loaded`, `loaded_at`) VALUES ('직원인사규정.pdf', 'doc_직원인사규정.pdf', 'res/pdf/직원인사규정.pdf', 0, null);
INSERT INTO `document` (`original_file_name`, `stored_file_name`, `file_path`, `is_loaded`, `loaded_at`) VALUES ('휴직자 복무관리 지침.pdf', 'doc_휴직자 복무관리 지침.pdf', 'res/pdf/휴직자 복무관리 지침.pdf', 0, null);
