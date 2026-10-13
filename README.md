# 귀뚜라미 IoT 멀티 매니저 for Home Assistant

귀뚜라미 **각방제어기 + IoT 멀티 매니저**를 Home Assistant에서 방별 Climate 엔티티로 제어하기 위한 비공식 사용자 통합 구성요소입니다.

> [!IMPORTANT]
> **권리포기각서:** 본 프로젝트는 개인이 만든 비공식 프로젝트입니다. 본 프로젝트의 개발 및 저장소 운영은 **(주)귀뚜라미 및 그 계열사와 무관하며**, 공식 지원이나 승인을 받지 않았습니다. 본 프로젝트는 어떠한 보증도 없이 제공되며, 설치와 사용으로 발생하는 책임은 각 사용자에게 있습니다.

## 지원 기능

- 멀티 매니저 계정의 각방 조절기 자동 검색
- `deviceTopic + eachRoomID` 조합별 Climate 엔티티 생성
- 방별 현재 온도 및 설정 온도 조회
- 방별 `난방 중` · `대기` · `꺼짐` 상태 및 Home Assistant 히스토리 기록
- 방별 난방 켜기·끄기
- 방별 희망 온도 설정(5~45°C)
- 방별 외출 모드
- HTTPS 기반 클라우드 폴링

단독 온도조절기, 목욕 모드, 예약 모드 및 MQTT 연결은 지원하지 않습니다.

## 설치

### HACS

HACS 사용자 저장소에 아래 주소를 Integration 유형으로 추가한 뒤 설치합니다.

```text
https://github.com/Akarow77/ha-component-kiturami-multi
```

설치가 끝나면 Home Assistant를 재시작합니다.

### 수동 설치

`custom_components/kiturami_multi` 폴더를 Home Assistant의 `/config/custom_components/kiturami_multi`로 복사하고 Home Assistant를 재시작합니다.

## 설정

통합 구성요소 추가 화면에서 `귀뚜라미 IoT 멀티 매니저`를 선택하고 멀티 매니저 앱의 아이디와 비밀번호를 입력합니다.

한 개의 멀티 매니저 아래에 있는 각 방은 별도의 Climate 엔티티로 생성됩니다. API 응답에 방 이름이 없으면 `각방 01`, `각방 02` 형식으로 표시됩니다. 상태 동기화 간격의 기본값은 1분입니다.

Climate 엔티티의 `hvac_action` 속성으로 난방 중·대기·꺼짐이 표시되며 Home Assistant Recorder와 히스토리에 자동으로 남습니다. 멀티 매니저 API가 실제 버너 점화 신호를 제공하지 않아, `난방 중`은 공식 앱과 동일하게 현재 온도가 설정 온도보다 낮은지로 판단한 난방 요청 상태입니다.

## 제한 사항

이 프로젝트는 공개되지 않은 제조사 API를 사용합니다. API는 사전 고지 없이 변경되거나 차단될 수 있으며, 제조사의 앱 또는 서버 업데이트에 따라 통합이 동작하지 않을 수 있습니다.

초기 구현은 `귀뚜라미 IoT 멀티 매니저 2.8.4`의 통신 구조를 정적 분석해 작성했습니다. 실제 계정과 기기 조합에 따라 응답 필드가 다를 수 있습니다.

## 개발

```bash
python -m unittest discover -s tests -v
python -m compileall -q custom_components tests
ruff check .
ruff format --check .
```

변경 사항은 [CHANGELOG.md](CHANGELOG.md)에서 확인할 수 있습니다.
