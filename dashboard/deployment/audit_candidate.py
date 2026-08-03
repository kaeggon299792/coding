import importlib.util
import sys
import re
from pathlib import Path

sys.path.insert(0, ".")

spec = importlib.util.spec_from_file_location("candidate", "deployment/app-page-repair-20260803.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
expected = {
    "company_news_page",
    "legislation_page",
    "create_action_item_route",
    "community_board_page",
    "community_post_page",
    "company_detail_page",
}
available = {rule.endpoint for rule in module.app.url_map.iter_rules()}
print(f"route_count={len(module.app.url_map._rules)}")
print(f"expected_present={sorted(expected & available)}")
print(f"expected_missing={sorted(expected - available)}")

referenced = set()
for template in Path("templates").rglob("*.html"):
    text = template.read_text(encoding="utf-8")
    referenced.update(re.findall(r"url_for\(\s*['\"]([^'\"]+)", text))
print(f"template_endpoints_missing={sorted(referenced - available)}")
for rule in module.app.url_map.iter_rules():
    if rule.endpoint in expected:
        print(f"route={rule.endpoint} {rule.rule} {sorted(rule.methods)}")
