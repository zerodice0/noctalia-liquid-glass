# Noctalia Liquid Glass

Noctalia **native 5.0.1 + Umbriel**용 실험적 Liquid Glass. 반투명 테마뿐 아니라 Umbriel의 배경 합성 단계에 가장자리 굴절, RGB 색 분산, 얇은 하이라이트를 추가합니다. 글자와 아이콘 자체에는 굴절을 적용하지 않습니다.

확정 프리셋은 `dark`입니다. 다크 색상에 바 22%, 독 20%, 패널 배경 20%, 내부 카드 16%, Ghostty 배경 55% 불투명도를 사용합니다. 이 값들은 개별 레이어의 알파이며, 카드와 패널이 겹치면 최종 불투명도는 더 높습니다. Ghostty 글자 색상과 창 전체 불투명도는 유지합니다.

[Liquid Glass V2 영상](https://www.reddit.com/r/cachyos/comments/1w9uqos/liquid_glass_v2/)에서 영감을 받았습니다. 원본은 KDE Plasma이며 이 프로젝트는 해당 설정이나 KWin 플러그인의 복제본이 아닙니다. 영상의 위젯 배치를 그대로 복제하지 않고 기존 Noctalia 구성에 광학 효과를 더합니다.

## 호환성과 제한

- 기준: Noctalia 5.0.1, Umbriel `fd73faef31d53b3336e9407d67a4962855bb6d1a`, wlroots **0.20.x**, OpenGL ES.
- Arch/CachyOS의 `umbriel.service` 사용자 세션을 전제로 합니다. Hyprland/Niri/KWin 및 이전 Quickshell 기반 Noctalia에서는 이 설치 절차를 사용하지 마세요.
- 시스템 `/usr/bin/umbriel`, `/usr/bin/noctalia`는 덮어쓰지 않습니다. 사용자 디렉터리에 별도 바이너리를 설치합니다.
- 원래 실행 파일을 PATH에서 찾아 런처의 복구 경로로 보관하므로 `/usr/local/bin/umbriel` 설치도 지원합니다. 기존 systemd 사용자 세션이 필요합니다.
- 일반 창 기본값은 블러 + 92% 불투명도입니다. 기존 기기별 창 규칙이 기본값보다 우선합니다. 배경만 투명하게 할 수 없는 앱은 글자·이미지도 8% 투명해지는 절충안입니다.
- Ghostty는 창 전체 불투명도 100%, 배경만 `dark` 55%, `light` 60%로 설정하고 명시적 셀 배경에도 투명도를 적용합니다. 폰트·키 바인딩은 유지하고 색상은 기존 Noctalia 테마 동기화를 따릅니다. 기존 Ghostty 설정 파일이 있는 기기에만 적용합니다.
- 독립형 대시보드를 유지하면서 열릴 때 키보드 포커스를 요청합니다. 패널과 내부 카드의 알파를 별도 조절하며, Umbriel 패치는 알파 경계 기반 내부 카드 굴절 및 overview 작업공간 배경 효과를 추가합니다. 모든 위젯에 독립적인 광학 표면을 제공하는 방식은 아닙니다.
- 게임/영상 content type 및 Steam 게임·gamescope·mpv·VLC는 불투명/블러 없음 예외입니다. Umbriel 자체가 전체화면의 규칙 불투명도를 무시합니다. 앱이 제공하는 Ghostty 등의 배경 알파는 전체화면에서도 남을 수 있습니다. 모든 게임/영상 앱이 content type을 제공하지는 않습니다.
- 광학 거리 설정은 물리 픽셀입니다. 프랙셔널 배율에서 모양은 유지되지만 체감 굴절 폭은 달라집니다.
- GPD WIN mini는 경량 프리셋을 제공하지만 **실기기 성능·전력·배터리는 미검증**입니다. 동일 계열 데스크톱 설치가 필요합니다.
- wlroots ABI/Noctalia 설정 변경 시 패치 재검토와 재빌드가 필요합니다. 최신 Umbriel로 자동 리베이스하지 않습니다.

## 설치

기존 Noctalia/Umbriel 세션이 정상 작동하는 환경에서 실행합니다. 아래 추가 의존성이 없으면 Arch 패키지 관리자로 설치하세요.

```sh
git clone https://github.com/zerodice0/noctalia-liquid-glass.git
cd noctalia-liquid-glass
sudo pacman -S --needed base-devel git meson ninja pkgconf python python-pip tomlplusplus nlohmann-json stb wayland-protocols
/usr/bin/python -m venv .venv
.venv/bin/pip install -r requirements.txt
./scripts/build.sh
./scripts/build-noctalia.sh
./scripts/install-runtime.sh
./glass plan dark
./glass apply dark
```

나머지 라이브러리는 Umbriel 및 네이티브 Noctalia 빌드 의존성입니다. `nlohmann-json` 또는 필요한 `stb` 헤더가 없는 경우 빌드 스크립트가 고정 SHA256을 확인한 헤더 패키지를 `.build/deps`에 로컬 추출할 수 있습니다. 두 빌드 스크립트 앞에 `GLASS_JOBS=2`를 붙여 동시 작업 수를 줄일 수 있습니다.

**열린 작업을 저장한 뒤 로그아웃하고 Umbriel 세션에 다시 로그인하세요.** 적용 스크립트는 세션을 종료하거나 재시작하지 않습니다. 첫 적용 직후 Noctalia 모양은 바뀌지만, 새 굴절 렌더러는 다음 로그인부터 실행됩니다. 기존 바이너리에서는 낮아진 불투명도 때문에 로그인 전까지 블러가 다르게 보일 수 있습니다.

다음 로그인 후 확인:

```sh
~/.local/share/noctalia-liquid-glass/runtime/bin/umbriel --version
readlink /proc/"$(systemctl --user show umbriel.service -p MainPID --value)"/exe
systemctl --user show umbriel.service -p ExecStart
./glass status
```

설치 버전은 Umbriel `+liquid-glass.3`, Noctalia `+liquid-glass.2`이며, 실행 중 프로세스 경로도 위 runtime 바이너리여야 합니다. Umbriel 바이너리 또는 설정 검증이 실패하면 런처는 패키지 Umbriel로 돌아갑니다. 실행 도중 GPU 오류까지 자동 복구하는 기능은 아닙니다. 기존 autostart의 정확히 `noctalia`인 항목만 새 셸 런처로 교체합니다. 다른 방식으로 셸을 시작하는 기기는 `~/.local/bin/noctalia-liquid-glass`를 사용하도록 별도 설정해야 합니다.

## 프리셋 전환과 복구

로그인 화면은 별도입니다. `./glass greeter-sync`로 배경화면·팔레트·프로필 사진을 동기화할 수 있습니다. 관리자 인증·백업·복구 및 굴절/불투명도 지원 범위는 [GREETER.md](GREETER.md)를 참고하세요.

Ghostty는 적용/복구 후 `Ctrl+Shift+,`로 설정을 다시 읽으세요. 이 프로젝트는 설정 마지막의 표시된 관리 블록만 바꾸고, 복구 시 그 블록만 제거합니다. 기존 설정과 나중에 바꾼 글꼴 등의 값은 보존합니다. [Ghostty 설정 문서](https://ghostty.org/docs/config/reference#background-opacity-cells)

| 명령 | 용도 |
| --- | --- |
| `./glass apply glass-dark` | 선명한 모서리 굴절, 낮은 색 분산, Ghostty 배경 불투명도 38% |
| `./glass apply dark` | 확정된 낮은 불투명도의 다크 테마 |
| `./glass apply light` | 밝은 바탕과 낮은 불투명도의 라이트 테마 |
| `./glass apply gpd-dark` / `gpd-light` | 해당 모드의 경량 GPD 프리셋 |
| `./glass apply frosted-dark` / `frosted-light` | 해당 모드에서 굴절 끄기 |
| `./glass apply desktop` | 실시간 배경, 강한 가장자리 굴절과 색 분산 |
| `./glass apply gpd` | 1패스 블러, 셸 배경 캐시, 색 분산 끄기 |
| `./glass apply frosted` | 같은 레이아웃에서 굴절 없이 블러만 사용 |
| `./glass apply original` | 저장된 원래 외형 프리셋; 커스텀 런타임은 유지 |
| `./glass save my-theme` | 현재 외형 중 관리 대상 항목만 새 프리셋으로 저장 |
| `./glass restore` | 이 기기의 최초 적용 전 외형과 세션 실행 명령으로 복구 |

bar·dock에서는 배경 불투명도와 테두리 색상·두께만 관리합니다. 크기·간격·모서리 반경·활성화·확대 효과와 패널 배치는 현재 사용자 설정을 유지합니다. 이전 버전의 프로필이나 복구 기록에 남은 해당 설정도 무시하므로, `apply`·모드 전환·`restore`가 개인 배치를 되돌리지 않습니다.

이미 Noctalia 설정에 저장된 개별 모서리 값은 그대로 유지됩니다. 전체 반지름을 바꿔도 반영되지 않으면 `radius_top_left`, `radius_top_right`, `radius_bottom_left`, `radius_bottom_right`의 개별 지정을 해제하세요. 화면 가장자리와 이어지는 곡선은 `margin_edge = 0`이고 `concave_edge_corners = true`일 때 표시됩니다.

패치된 세션에서 프리셋 전환은 설정 감시로 반영됩니다. `restore` 후 패키지 바이너리로의 전환은 다음 로그인에 이뤄집니다. 현재 실행 중인 패치가 읽을 수 있도록 원래 설정만 include하는 작은 설정 파일을 남깁니다. 원래 파일과 다른 무관한 폰트·배경화면 변경은 유지하며, 테마가 관리한 항목은 적용 전 값으로 돌립니다.

모드별 프리셋은 Noctalia의 라이트/다크 전환 후 `liquid_glass` 사용자 템플릿의 `follow-mode` 후처리로 같은 계열의 재질 설정을 선택합니다. `auto` 모드는 자동 설정을 유지합니다. 레거시 `desktop`, `gpd`, `frosted`는 색상 모드를 강제하지 않습니다. 템플릿 후처리는 저장소 경로를 사용하므로 저장소를 옮겼다면 `apply`를 다시 실행하세요. 높은 투명도의 라이트 모드는 배경에 따라 글자 대비가 부족할 수 있으므로 기본 권장은 `dark`입니다.

배경화면, 모니터, 키보드, 키 바인딩, 계정, 클립보드, 플러그인 데이터는 Git에 저장하지 않습니다. `original`도 전체 데스크톱 복제본이 아닌 외형 프리셋입니다. 다른 테마를 쓰기 전 `save`하고, 복원할 때 해당 프리셋을 `apply`하세요. 색상 팔레트와 폰트는 기기의 기존 설정을 유지합니다.

GPD WIN mini에서는 저장소를 복제한 뒤 **그 기기에서 빌드·설치**하고 `./glass apply gpd-dark`를 실행하세요. 데스크톱의 전체 설정 디렉터리나 바이너리를 복사하지 마세요. 패널 이름/입력/배율은 기기 설정을 그대로 사용합니다. 모니터별 Noctalia 바 설정은 `bar.default`보다 우선하므로 별도 조정이 필요할 수 있습니다.

## 파일과 백업

기본 경로이며 XDG 디렉터리 변수를 지원합니다.

- `~/.local/share/noctalia-liquid-glass/runtime/`: 별도 런타임
- `~/.config/noctalia-liquid-glass/umbriel.toml`: 원래 Umbriel 설정을 include하는 효과 설정
- `~/.config/noctalia-liquid-glass/colors.template.toml`, `colors.toml`: Noctalia 색상과 재질 알파 동기화; 기존 Umbriel 색상 템플릿과 다른 출력 사용
- `~/.local/state/noctalia/settings.toml`: 테마가 관리하는 외형 값만 수정
- `~/.local/bin/umbriel-liquid-glass`: 검증 후 실행하는 런처
- `~/.local/bin/noctalia-liquid-glass`: 패치된 Noctalia 셸 런처
- `~/.config/systemd/user/umbriel.service.d/90-liquid-glass.conf`: 다음 세션의 실행 명령
- `~/.local/state/noctalia-liquid-glass/backups/`: 적용·복구 직전 로컬 백업 (`files.json`, 원본 바이트 base64)

백업에는 개인 경로 등이 포함될 수 있습니다. Git에 올리지 마세요. 기존 `~/.config/umbriel/config.toml`은 수정하지 않습니다. Umbriel의 배열 include 병합은 교체 방식이므로 기존 레이어 규칙을 효과 설정에 함께 복사합니다. **원본 레이어 규칙을 나중에 수정했다면 `apply`를 다시 실행**해 반영하세요.

로그인 문제 시 TTY에서 저장소의 `./glass restore`를 실행한 후 다시 로그인하세요. 빌드 산출물은 복구 후에도 남으므로 재적용할 수 있습니다. `systemctl --user restart umbriel`은 앱을 종료하므로 작업 중 실행하지 마세요.

## 검증

```sh
meson test -C .build/umbriel/build --print-errorlogs
.venv/bin/python tests/theme_test.py
# 추가 테스트 도구: grim, wtype, python-pillow, dbus
./tests/render.sh
/usr/bin/python3 tests/noctalia_smoke.py
GLASS_TEST_PROFILE=dark /usr/bin/python3 tests/noctalia_smoke.py
/usr/bin/python3 tests/window_render.py
```

실제 GPU를 사용하는 별도 headless Wayland 세션에서 합성 배경/알파 카드로 굴절·색 분산, 전경 글자 유지, 효과 해제 시 원본 복귀를 검사합니다. 라이브/캐시 블러, 150% 배율, 90도 회전을 포함합니다. Noctalia 스모크 테스트는 임시 설정과 별도 세션 버스에서 바·독·런처·독립형 대시보드를 실행하고 방향키 탐색, Escape/재열기 및 내부 카드 굴절을 검사합니다. 테스트 이미지와 로그는 Git에서 제외된 `artifacts/`에 저장됩니다.

초기 RX 9070 XT 환경에서 upstream 단위 테스트 50개, 테마 관리 테스트 3개, 렌더링 시나리오 4개를 통과했습니다. 이는 전체 데스크톱 장기 안정성/성능 보증이 아닙니다.

일반 불투명 xdg 앱의 92% 규칙 적용 후 굴절 및 원본 복귀, 게임 content type의 효과 제외도 별도 렌더링 테스트로 확인했습니다.

## 소스와 라이선스

Umbriel 원본은 [noctalia-dev/umbriel](https://github.com/noctalia-dev/umbriel)에서 고정 커밋으로 받습니다. 변경 내용은 `patches/umbriel-liquid-glass.patch`에 보관합니다. 새 코드 및 파생 부분의 MIT 고지는 `LICENSE`, 원본 프로젝트 고지는 `NOTICE`를 참고하세요.

Noctalia 원본은 [noctalia-dev/noctalia](https://github.com/noctalia-dev/noctalia)에서 `noctalia-upstream.json`의 고정 커밋으로 받으며, 변경 내용은 `patches/noctalia-liquid-glass.patch`에 보관합니다. 바이너리·원본 설정·로컬 백업·화면 캡처는 공개 저장소에 포함하지 않습니다.
