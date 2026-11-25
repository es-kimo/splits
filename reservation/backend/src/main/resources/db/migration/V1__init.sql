-- MySQL 8과 H2(MySQL 모드) 양쪽에서 그대로 도는 문법만 쓴다.

CREATE TABLE club (
    id             BIGINT       NOT NULL AUTO_INCREMENT,
    name           VARCHAR(60)  NOT NULL,
    access_token   VARCHAR(64)  NOT NULL,
    admin_pin_hash VARCHAR(100) NOT NULL,
    created_at     DATETIME(6)  NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uk_club_access_token UNIQUE (access_token)
);

CREATE TABLE club_member (
    id         BIGINT      NOT NULL AUTO_INCREMENT,
    club_id    BIGINT      NOT NULL,
    name       VARCHAR(40) NOT NULL,
    active     BOOLEAN     NOT NULL,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uk_club_member_name UNIQUE (club_id, name),
    CONSTRAINT fk_club_member_club FOREIGN KEY (club_id) REFERENCES club (id)
);

-- 한 번의 예약 오픈(예: "12월 예약")이 한 회차다.
CREATE TABLE booking_round (
    id            BIGINT        NOT NULL AUTO_INCREMENT,
    club_id       BIGINT        NOT NULL,
    title         VARCHAR(80)   NOT NULL,
    opens_at      DATETIME(6)   NOT NULL,
    booking_url   VARCHAR(500)  NULL,
    court_links   VARCHAR(2000) NULL,
    -- 현황판이 바뀔 때마다 1씩 오른다. 폴링하는 화면이 바뀐 게 없으면 304를 받는다.
    board_version BIGINT        NOT NULL,
    archived      BOOLEAN       NOT NULL,
    created_at    DATETIME(6)   NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_booking_round_club FOREIGN KEY (club_id) REFERENCES club (id)
);

-- 계획: "누가 어느 시간을 맡는다"
CREATE TABLE plan_slot (
    id                 BIGINT      NOT NULL AUTO_INCREMENT,
    round_id           BIGINT      NOT NULL,
    slot_no            INT         NOT NULL,
    play_date          DATE        NOT NULL,
    start_hour         INT         NOT NULL,
    end_hour           INT         NOT NULL,
    -- NULL이면 아무 코트
    court_pref         INT         NULL,
    assignee_member_id BIGINT      NULL,
    -- NEED_HELP(맡은 사람이 못 함) 또는 CLOSED(마감 확인)
    fail_kind          VARCHAR(16) NULL,
    fail_member_id     BIGINT      NULL,
    fail_at            DATETIME(6) NULL,
    PRIMARY KEY (id),
    CONSTRAINT uk_plan_slot_no UNIQUE (round_id, slot_no),
    CONSTRAINT fk_plan_slot_round FOREIGN KEY (round_id) REFERENCES booking_round (id),
    CONSTRAINT fk_plan_slot_assignee FOREIGN KEY (assignee_member_id) REFERENCES club_member (id)
);

-- 실제 예약: "누가 어느 코트를 잡았다"
CREATE TABLE reservation (
    id                     BIGINT      NOT NULL AUTO_INCREMENT,
    round_id               BIGINT      NOT NULL,
    play_date              DATE        NOT NULL,
    start_hour             INT         NOT NULL,
    end_hour               INT         NOT NULL,
    court_no               INT         NOT NULL,
    booker_member_id       BIGINT      NOT NULL,
    reported_by_member_id  BIGINT      NOT NULL,
    slot_id                BIGINT      NULL,
    -- 살아 있는 예약은 1, 취소되면 NULL. UNIQUE에서 NULL은 서로 겹치지 않으므로
    -- "살아 있는 예약끼리만 중복 금지"를 부분 인덱스 없이 표현한다.
    active_key             INT         NULL,
    created_at             DATETIME(6) NOT NULL,
    cancelled_at           DATETIME(6) NULL,
    cancelled_by_member_id BIGINT      NULL,
    PRIMARY KEY (id),
    CONSTRAINT uk_reservation_court_time UNIQUE (round_id, play_date, start_hour, court_no, active_key),
    CONSTRAINT uk_reservation_slot UNIQUE (slot_id, active_key),
    CONSTRAINT fk_reservation_round FOREIGN KEY (round_id) REFERENCES booking_round (id),
    CONSTRAINT fk_reservation_slot FOREIGN KEY (slot_id) REFERENCES plan_slot (id),
    CONSTRAINT fk_reservation_booker FOREIGN KEY (booker_member_id) REFERENCES club_member (id),
    CONSTRAINT fk_reservation_reporter FOREIGN KEY (reported_by_member_id) REFERENCES club_member (id)
);

-- 이름 고르기는 본인 확인이 아니므로, 누가 무엇을 바꿨는지 남긴다.
CREATE TABLE event_log (
    id              BIGINT       NOT NULL AUTO_INCREMENT,
    club_id         BIGINT       NOT NULL,
    round_id        BIGINT       NULL,
    actor_member_id BIGINT       NULL,
    actor_name      VARCHAR(40)  NOT NULL,
    type            VARCHAR(40)  NOT NULL,
    detail          VARCHAR(500) NOT NULL,
    created_at      DATETIME(6)  NOT NULL,
    PRIMARY KEY (id)
);

CREATE INDEX ix_event_log_round ON event_log (round_id, id);
