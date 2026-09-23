import json

# naive 4x3-ish grid for 10 unit circles
pts = [(float(i % 4), float(i // 4)) for i in range(10)]
print(json.dumps({"positions": pts}))
