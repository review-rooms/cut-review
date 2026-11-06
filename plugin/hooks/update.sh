#!/bin/sh
# Once a day, in the background: pull the newest cut-review from GitHub (the plugin's skill and the uvx CLI), so
# `cut-review page` builds rooms from the latest page. Set CUT_REVIEW_NO_AUTO_UPDATE=1 to turn it off.
[ -n "$CUT_REVIEW_NO_AUTO_UPDATE" ] && exit 0
stamp="${XDG_CACHE_HOME:-$HOME/.cache}/cut-review/last-update"
mkdir -p "$(dirname "$stamp")" || exit 0
[ -n "$(find "$stamp" -mmin -1440 2>/dev/null)" ] && exit 0
touch "$stamp"
(
  command -v claude >/dev/null && claude plugin marketplace update cut-review && claude plugin update cut-review@cut-review
  command -v uvx >/dev/null && uvx --refresh-package cut-review --from git+https://github.com/review-rooms/cut-review cut-review --version
) >"$(dirname "$stamp")/last-update.log" 2>&1 </dev/null &
exit 0
