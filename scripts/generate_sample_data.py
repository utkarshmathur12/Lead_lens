"""Generate a SYNTHETIC, deliberately messy lead file (no real businesses or people).

Includes the problems real exports have: duplicates with different spellings, mixed
number formats, invalid/generic emails, missing fields, and franchise lookalikes.
"""
import csv
import random
from pathlib import Path

random.seed(42)
OUT = Path(__file__).resolve().parent.parent / "data" / "sample_leads.csv"

INDUSTRIES = {
    "HVAC": ["Comfort", "Air", "Climate", "Heating & Cooling"], "Plumbing": ["Rooter", "Pipe", "Flow", "Plumbing"],
    "Landscaping": ["Greenscape", "Lawn", "Gardens", "Turf"], "Roofing": ["Summit Roofing", "Shield Roof", "Apex Roofing"],
    "Electrical": ["Spark", "Volt", "Circuit", "Electric"], "Pest Control": ["Bug Busters", "Pest Guard", "Critter"],
    "Auto Repair": ["Motors", "Garage", "Auto Care", "Tire & Brake"], "Dental": ["Family Dental", "Smiles", "Dentistry"],
    "Accounting": ["Tax & Advisory", "CPA Group", "Bookkeeping"], "Software": ["Labs", "Systems", "Cloud"],
    "Restaurant": ["Grill", "Kitchen", "Diner"], "Retail": ["Outfitters", "Mercantile", "Goods"],
}
SURNAMES = ["Miller", "Nguyen", "Garcia", "Johnson", "Patel", "Brown", "Kowalski", "Rossi", "Hughes", "Carter",
            "Lopez", "Schmidt", "Bennett", "Murphy", "Ortiz", "Clark", "Reyes", "Foster", "Hayes", "Sullivan"]
FIRST = ["Tom", "Maria", "David", "Linda", "Raj", "Susan", "Mike", "Karen", "James", "Priya", "Robert", "Ana"]
CITIES = {"TX": ["Austin", "Dallas", "Plano"], "FL": ["Tampa", "Orlando", "Naples"], "OH": ["Columbus", "Dayton"],
          "NC": ["Raleigh", "Charlotte"], "AZ": ["Phoenix", "Tempe"], "CO": ["Denver", "Boulder"],
          "GA": ["Atlanta", "Marietta"], "TN": ["Nashville", "Franklin"]}
STATE_NAMES = {"TX": "Texas", "FL": "Florida", "OH": "Ohio", "NC": "North Carolina", "AZ": "Arizona",
               "CO": "Colorado", "GA": "Georgia", "TN": "Tennessee"}
DESCS = ["Family owned and operated {ind} company serving the region.", "Full-service {ind} provider with a loyal customer base.",
         "Founded by {last} and still run by the family.", "Licensed and insured {ind} specialists.",
         "Locally owned {ind} business, trusted since {yr}.", "Regional {ind} provider.", ""]


def money(x):
    return random.choice([f"${x:,.0f}", f"{x/1e6:.1f}M", f"${x/1e6:.1f}M", f"{int(x/1000)}k"])


rows = []
for i in range(260):
    ind = random.choice(list(INDUSTRIES))
    last = random.choice(SURNAMES)
    st = random.choice(list(CITIES))
    name = f"{last} {random.choice(INDUSTRIES[ind])}"
    suffix = random.choice(["", " LLC", " Inc.", " Co"])
    yr = random.choice([1962, 1975, 1984, 1991, 1998, 2004, 2010, 2016, 2021, None])
    emp = random.choice([3, 8, 12, 25, 40, 70, 120, 300, None])
    rev = random.choice([4e5, 1.4e6, 2.8e6, 5.5e6, 9e6, 14e6, 40e6, None])
    domain = f"{last.lower()}{ind.split()[0].lower()}{random.randint(1, 99)}.example"
    owner = f"{random.choice(FIRST)} {last}" if random.random() < 0.6 else ""
    local = random.choice(["info", "contact", "office", owner.split()[0].lower() if owner else "info"])
    email = f"{local}@{domain}" if random.random() < 0.8 else ""
    if email and random.random() < 0.06:
        email = email.replace("@", "")  # broken
    phone = random.choice([f"({random.randint(200, 989)}) {random.randint(200, 989)}-{random.randint(1000, 9999)}",
                           f"{random.randint(200, 989)}.{random.randint(200, 989)}.{random.randint(1000, 9999)}",
                           f"+1 {random.randint(200, 989)} {random.randint(200, 989)} {random.randint(1000, 9999)}", ""])
    desc = random.choice(DESCS).format(ind=ind.lower(), last=last, yr=yr or 1990)
    if random.random() < 0.07:
        desc += " Proud franchisee of a national brand."
    rows.append({
        "Company Name": name + suffix, "Website": random.choice([f"https://www.{domain}", domain, f"http://{domain}/"]),
        "Industry": ind, "City": random.choice(CITIES[st]), "State": random.choice([st, STATE_NAMES[st]]),
        "Employees": emp if emp else "", "Estimated Revenue": money(rev) if rev else "", "Phone": phone,
        "Email": email, "Owner": owner, "Year Founded": yr or "",
        "Rating": round(random.uniform(3.2, 5.0), 1) if random.random() < 0.85 else "",
        "Reviews": random.randint(2, 400) if random.random() < 0.85 else "", "Description": desc,
    })

# inject ~40 duplicates with spelling/format drift
for r in random.sample(rows, 40):
    d = dict(r)
    d["Company Name"] = d["Company Name"].replace(" LLC", "").replace(" Inc.", "").replace(" Co", "") + random.choice([" LLC", ", Inc", ""])
    if random.random() < 0.5:
        d["Website"] = ""
    if random.random() < 0.5:
        d["Email"] = ""
    rows.append(d)
random.shuffle(rows)
OUT.parent.mkdir(exist_ok=True)
with open(OUT, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
print(f"Wrote {len(rows)} rows to {OUT}")
