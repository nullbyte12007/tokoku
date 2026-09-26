#!/usr/bin/env bash
# Push repo portofolio ini ke GitHub.
#
# Butuh file kredensial (JANGAN di-commit):
#   ~/.openclaw/workspace/credentials-github.json
#   {
#     "username": "akun-github",
#     "token": "PERSONAL_ACCESS_TOKEN",
#     "repo": "kaizen-ai-portfolio",
#     "visibility": "private",          # atau "public"
#     "email": "opsional@email"         # buat identitas commit
#   }
#
# Pakai:
#   ./setup-github.sh
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
CRED="${GITHUB_CRED:-$HOME/.openclaw/workspace/credentials-github.json}"

[ -f "$CRED" ] || { echo "✖ kredensial tidak ada: $CRED"; exit 1; }

read -r USER TOKEN REPO VIS EMAIL < <(python3 - "$CRED" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
u = d["username"]
print(u, d["token"], d.get("repo", "kaizen-ai-portfolio"),
      d.get("visibility", "private"),
      d.get("email", f"{u}@users.noreply.github.com"))
PY
)

cd "$REPO_DIR"

# identitas commit (repo-local saja)
git config user.name  "M Yusuf Saleh"
git config user.email "$EMAIL"

echo "→ memeriksa repo '$REPO'..."
exists=$(curl -s -o /dev/null -w '%{http_code}' \
  "https://api.github.com/repos/$USER/$REPO" -H "Authorization: Bearer $TOKEN")
if [ "$exists" = "200" ]; then
  echo "  ✔ repo sudah ada, langsung push"
  code=422
else
  code=$(curl -s -o /tmp/gh_repo.json -w '%{http_code}' \
    -X POST https://api.github.com/user/repos \
    -H "Authorization: Bearer $TOKEN" \
    -H "Accept: application/vnd.github+json" \
    -d "{\"name\":\"$REPO\",\"private\":$([ "$VIS" = "private" ] && echo true || echo false)}")
fi

case "$code" in
  201) echo "  ✔ repo dibuat ($VIS)";;
  422) echo "  ℹ repo sudah ada, lanjut push";;
  401|403) echo "  ✖ token ditolak (HTTP $code) — cek scope Contents/Administration"; exit 1;;
  *) echo "  ⚠ respons tidak terduga (HTTP $code) — lanjut coba push";;
esac

# remote "bersih" (token TIDAK disimpan di .git/config)
git remote remove origin 2>/dev/null || true
git remote add origin "https://github.com/$USER/$REPO.git"

echo "→ push ke $USER/$REPO ..."
git push "https://$USER:$TOKEN@github.com/$USER/$REPO.git" HEAD:main

echo
echo "✔ selesai: https://github.com/$USER/$REPO"
echo "  (token tidak tersimpan di .git/config — aman)"