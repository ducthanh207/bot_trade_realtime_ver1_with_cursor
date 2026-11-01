#!/bin/bash
# Tự động deploy bot trên VPS. GitHub Actions (.github/workflows/deploy-vps.yml)
# gửi file này qua SSH rồi chạy bằng `bash -s`, nên luôn chạy bản mới nhất của script.
#
# Có thể chạy tay trên VPS:  BOT_DIR=~/Bot_VPS_Realtime_ver1_11_3_26 bash scripts/auto_deploy.sh
#
# An toàn cho bot đang chạy thật:
#   - Không bao giờ đụng .env, paper_state.json, data/ (đều không nằm trong git).
#   - Sao lưu paper_state.json + data/ trước mỗi lần deploy (giữ 10 bản gần nhất).
#   - Chỉ cập nhật kiểu fast-forward. VPS có file sửa tay hoặc lịch sử lệch thì DỪNG, không restart.
#   - Code mới lỗi cú pháp, hoặc bot không chạy lại được sau restart, thì quay về commit cũ.

set -euo pipefail

BOT_DIR="${BOT_DIR:-$HOME/Bot_VPS_Realtime_ver1_11_3_26}"
SERVICE="${SERVICE:-bot-live}"
BRANCH="${BRANCH:-main}"
BACKUP_ROOT="${BACKUP_ROOT:-$HOME/deploy_backups}"
KEEP_BACKUPS=10
export GIT_TERMINAL_PROMPT=0   # không treo nếu git đòi mật khẩu

SUDO=""
if [ "$(id -u)" != "0" ]; then SUDO="sudo -n"; fi

log() { echo ">>> $*"; }
fail() { echo "!!! $*" >&2; exit 1; }

cd "$BOT_DIR" || fail "Không thấy thư mục bot: $BOT_DIR"
[ -d .git ] || fail "$BOT_DIR không phải git repo"

OLD="$(git rev-parse HEAD)"
log "Thư mục: $BOT_DIR  |  commit hiện tại: $(git log --oneline -1)"

# 1) Sao lưu trạng thái
TS="$(date +%Y%m%d_%H%M%S)"
B="$BACKUP_ROOT/$TS"
mkdir -p "$B"
[ -f paper_state.json ] && cp -a paper_state.json "$B/"
[ -d data ] && cp -a data "$B/"
echo "$OLD" > "$B/commit_cu.txt"
chmod 700 "$BACKUP_ROOT" "$B"
log "Đã sao lưu trạng thái vào $B"
# Xoá bản sao lưu cũ, giữ $KEEP_BACKUPS bản mới nhất
ls -1dt "$BACKUP_ROOT"/*/ 2>/dev/null | tail -n +$((KEEP_BACKUPS + 1)) | xargs -r rm -rf

# 2) Lấy code mới (chỉ fast-forward)
if ! git diff --quiet || ! git diff --cached --quiet; then
  git status --short
  fail "VPS có file trong git bị sửa tay. Không deploy, bot vẫn chạy code cũ. Xem docs/TU-DONG-DEPLOY.md mục 'Deploy báo lỗi'."
fi
git fetch --quiet origin "$BRANCH"
NEW="$(git rev-parse "origin/$BRANCH")"
if [ "$OLD" = "$NEW" ]; then
  log "Đã là commit mới nhất ($NEW). Không cần restart."
  exit 0
fi
git merge --ff-only "origin/$BRANCH" || fail "Không fast-forward được (lịch sử trên VPS lệch với GitHub). Không deploy, bot vẫn chạy code cũ."
log "Cập nhật $OLD -> $(git log --oneline -1)"
git --no-pager log --oneline "$OLD..$NEW" | head -20

RESTARTED=0
rollback() {
  echo "!!! $1. Quay về commit cũ $OLD" >&2
  git reset --hard --quiet "$OLD"   # chỉ đổi file trong git; .env, paper_state.json, data/ không bị đụng
  # Chỉ restart lại nếu đã restart bằng code mới; chưa restart thì bot vẫn đang chạy code cũ
  if [ "$RESTARTED" = "1" ]; then $SUDO systemctl restart "$SERVICE" || true; fi
  exit 1
}

# 3) Cài thư viện nếu requirements.txt đổi
PY="$BOT_DIR/.venv/bin/python"
[ -x "$PY" ] || rollback "Không thấy $PY"
if ! git diff --quiet "$OLD" "$NEW" -- requirements.txt; then
  log "requirements.txt thay đổi, đang pip install..."
  "$PY" -m pip install --quiet -r requirements.txt || rollback "pip install lỗi"
fi

# 4) Kiểm tra cú pháp các file .py thay đổi trước khi restart
CHANGED_PY="$(git diff --name-only --diff-filter=AM "$OLD" "$NEW" -- '*.py')"
if [ -n "$CHANGED_PY" ]; then
  # shellcheck disable=SC2086
  "$PY" -m py_compile $CHANGED_PY || rollback "Code mới lỗi cú pháp"
fi

# 5) Restart và kiểm tra bot chạy ổn
log "Restart $SERVICE..."
RESTARTED=1
$SUDO systemctl restart "$SERVICE"
sleep 20
if ! $SUDO systemctl is-active --quiet "$SERVICE"; then
  $SUDO journalctl -u "$SERVICE" -n 40 --no-pager || true
  rollback "Bot không chạy sau khi restart"
fi
# Restart=always có thể làm service "active" nhưng liên tục crash: kiểm tra số lần restart
RESTARTS="$($SUDO systemctl show "$SERVICE" -p NRestarts --value 2>/dev/null || echo 0)"
if [ "${RESTARTS:-0}" -gt 0 ]; then
  $SUDO journalctl -u "$SERVICE" -n 40 --no-pager || true
  rollback "Bot bị crash và tự khởi động lại $RESTARTS lần sau deploy"
fi

$SUDO systemctl status "$SERVICE" --no-pager | head -5
log "Deploy xong: $(git log --oneline -1)"
