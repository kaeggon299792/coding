import importlib
import sys
import urllib.error
import urllib.request

sys.path.insert(0, ".")
module = importlib.import_module("app")
base = "https://casino.shingoon.me"
skip = {"static", "robots_txt", "sitemap_xml", "healthz"}
results = []
for rule in sorted(module.app.url_map.iter_rules(), key=lambda item: item.rule):
    if "GET" not in rule.methods or "<" in rule.rule or rule.endpoint in skip:
        continue
    request = urllib.request.Request(base + rule.rule, headers={"User-Agent": "CASINO-IN-route-audit/1.0"})
    try:
        response = urllib.request.urlopen(request, timeout=20)
        status = response.status
        final_url = response.url
    except urllib.error.HTTPError as exc:
        status = exc.code
        final_url = exc.url
    except Exception as exc:
        status = "ERR"
        final_url = type(exc).__name__
    results.append((status, rule.endpoint, rule.rule, final_url))

for row in results:
    print("\t".join(map(str, row)))
print("FAILURES", sum(1 for status, *_ in results if status == "ERR" or int(status) >= 500))
