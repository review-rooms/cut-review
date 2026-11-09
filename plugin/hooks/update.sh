#!/bin/sh
# Once a day, in the background: pull the newest cut-review from GitHub (the plugin's skill and the uvx CLI), so
# `cut-review page` builds rooms from the latest page. Set CUT_REVIEW_NO_AUTO_UPDATE=1 to turn it off.
[ -n "$CUT_REVIEW_NO_AUTO_UPDATE" ] && exit 0
stamp="${XDG_CACHE_HOME:-$HOME/.cache}/cut-review/last-update"
mkdir -p "$(dirname "$stamp")" || exit 0
[ -n "$(find "$stamp" -mmin -1440 2>/dev/null)" ] && exit 0
(
  # the day's mark goes down only once both updates worked, so a failed one is tried again next session
  if command -v claude >/dev/null; then claude plugin marketplace update cut-review && claude plugin update cut-review@cut-review || exit 1; fi
  if command -v uvx >/dev/null; then uvx --refresh-package cut-review --from git+https://github.com/review-rooms/cut-review cut-review --version || exit 1; fi
  touch "$stamp"
) >"$(dirname "$stamp")/last-update.log" 2>&1 </dev/null &
exit 0
