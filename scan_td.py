import json, os, sys
sys.path.insert(0, '/Users/jeff/nfl-edge-v2')
import data as dl

path = os.path.join(os.path.dirname(dl.__file__), 'data', 'sgo_odds.json')
with open(path) as f:
    d = json.load(f)

events = d.get('data', [])
td_counts = {}
for e in events:
    odds = e.get('odds', {})
    for o in odds.values():
        mkt = dl.SGO_PROP_STATS.get(o.get('statID'))
        if mkt and ('td' in mkt or 'touchdown' in str(o.get('statID')).lower()):
            td_counts[mkt] = td_counts.get(mkt, 0) + 1

print('TD markets found:', td_counts)
print('Total events:', len(events))