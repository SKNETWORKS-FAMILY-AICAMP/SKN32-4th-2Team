-- =========================================================
-- RAG 챗봇 프로젝트 스키마 (MySQL 8.0)
-- =========================================================

CREATE DATABASE IF NOT EXISTS rag_chatbot
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_0900_ai_ci;

USE rag_chatbot;

-- ---------------------------------------------------------
-- 1. user : 사용자
-- ---------------------------------------------------------
CREATE TABLE `user` (
    `user_id`      VARCHAR(20)     NOT NULL COMMENT '사용자 ID',
    `passwd`       VARCHAR(255) NOT NULL COMMENT '암호화된 비밀번호',
    `name`         VARCHAR(50)  NOT NULL COMMENT '사용자 이름',
    `department`   VARCHAR(100) NOT NULL COMMENT '부서명',
    `is_admin`     BOOLEAN      NOT NULL DEFAULT FALSE COMMENT '관리자 여부',
    `is_disabled`  BOOLEAN      NOT NULL DEFAULT FALSE COMMENT '비활성화 여부',
    `is_deleted`   BOOLEAN      NOT NULL DEFAULT FALSE COMMENT '삭제 여부(소프트 삭제)',
    `created_at`   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성 일자',
    `updated_at`   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정 일자',
    `deleted_at`   DATETIME     NULL COMMENT '삭제 일자',
    PRIMARY KEY (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='사용자';


-- ---------------------------------------------------------
-- 2. user_login_history : 사용자 로그인 이력
-- ---------------------------------------------------------
CREATE TABLE `user_login_history` (
    `history_id` INT          NOT NULL AUTO_INCREMENT COMMENT '이력 ID',
    `user_id`    VARCHAR(20)     NOT NULL COMMENT '사용자 ID',
    `created_at` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성 일자(로그인 일시)',
    PRIMARY KEY (`history_id`),
    KEY `idx_login_history_user_id` (`user_id`),
    CONSTRAINT `fk_login_history_user`
        FOREIGN KEY (`user_id`) REFERENCES `user` (`user_id`)
        ON UPDATE CASCADE ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='사용자 로그인 이력';


-- ---------------------------------------------------------
-- 3. chatroom : 채팅방
-- ---------------------------------------------------------
CREATE TABLE `chatroom` (
    `chatroom_id`   CHAR(36)     NOT NULL COMMENT '채팅방 ID(UUID)',
    `user_id`       VARCHAR(20)  NOT NULL COMMENT '사용자 ID',
    `chatroom_name` VARCHAR(100) NOT NULL DEFAULT '새 대화' COMMENT '채팅방 이름',
    `created_at`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성 일자',
    `is_deleted`  BOOLEAN   NOT NULL DEFAULT FALSE COMMENT '삭제 여부',
    `deleted_at`  DATETIME  NULL COMMENT '삭제 일자',
    PRIMARY KEY (`chatroom_id`),
    KEY `idx_chatroom_user_id` (`user_id`),
    CONSTRAINT `fk_chatroom_user`
        FOREIGN KEY (`user_id`) REFERENCES `user` (`user_id`)
        ON UPDATE CASCADE ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='채팅방';


-- ---------------------------------------------------------
-- 4. chat : 채팅 대화 내용
-- ---------------------------------------------------------
CREATE TABLE `chat` (
    `chat_id`     INT           NOT NULL AUTO_INCREMENT COMMENT '채팅 ID',
    `chatroom_id` CHAR(36)      NOT NULL COMMENT '채팅방 ID(UUID)',
    `speaker`     ENUM('user','llm') NOT NULL COMMENT '화자(user/llm)',
    `message`     TEXT          NOT NULL COMMENT '대화 내용',
    `topic`       VARCHAR(100)  NULL COMMENT '주제',
    `created_at`  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성 일자',
    PRIMARY KEY (`chat_id`),
    KEY `idx_chat_chatroom_id` (`chatroom_id`),
    CONSTRAINT `fk_chat_chatroom`
        FOREIGN KEY (`chatroom_id`) REFERENCES `chatroom` (`chatroom_id`)
        ON UPDATE CASCADE ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='채팅 대화';


-- ---------------------------------------------------------
-- 5. document : RAG 문서
-- ---------------------------------------------------------
CREATE TABLE `document` (
    `doc_id`             INT          NOT NULL AUTO_INCREMENT COMMENT '문서 ID',
    `original_file_name` VARCHAR(255) NOT NULL COMMENT '실제 파일명(사용자가 업로드한 원본 파일명)',
    `stored_file_name`   VARCHAR(255) NOT NULL COMMENT '업로드 파일명(서버에 저장되는 파일명, 중복 방지용)',
    `file_path`          VARCHAR(500) NOT NULL COMMENT '저장 위치',
    `created_at`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성 일자',
    `is_loaded`   BOOLEAN      NOT NULL DEFAULT FALSE COMMENT '적재 여부',
    `loaded_at`   DATETIME     NULL COMMENT '적재 일자',
    `is_deleted`  BOOLEAN      NOT NULL DEFAULT FALSE COMMENT '삭제 여부',
    `deleted_at`  DATETIME     NULL COMMENT '삭제 일자',
    PRIMARY KEY (`doc_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='RAG 문서';


-- ---------------------------------------------------------
-- 6. chat_source : 채팅 답변의 근거 문서
-- ---------------------------------------------------------
CREATE TABLE `chat_source` (
    `source_id`  INT          NOT NULL AUTO_INCREMENT COMMENT '근거 문서 고유 번호',
    `chat_id`    INT          NOT NULL COMMENT '근거가 달린 채팅(llm 응답) ID',
    `doc_id`     INT          NULL COMMENT '문서 ID (document.doc_id 참조 값, 강한 FK는 아님)',
    `file_name`  VARCHAR(255) NOT NULL COMMENT '문서 파일명 (응답 시점 스냅샷)',
    `page`       INT          NULL COMMENT '문서 내 페이지 번호',
    `created_at` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성 일자',
    PRIMARY KEY (`source_id`),
    KEY `idx_chat_source_chat_id` (`chat_id`),
    CONSTRAINT `fk_chat_source_chat`
        FOREIGN KEY (`chat_id`) REFERENCES `chat` (`chat_id`)
        ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='채팅 답변의 근거 문서';

