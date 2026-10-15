"""Personalised first-touch drafts built from the same signals used for scoring."""


def _first(name):
    return (name or "").split()[0] if name else None


def draft(lead, sender="Utkarsh", firm="Caprae Capital"):
    owner = _first(lead.get("owner_name"))
    greet = f"Hi {owner}," if owner else "Hello,"
    company = lead["company"]
    where = f" in {lead['city']}" if lead.get("city") else ""
    hooks = []
    yr = lead.get("year_founded")
    if yr:
        hooks.append(f"building {company} since {yr}")
    if (lead.get("rating") or 0) >= 4.5 and (lead.get("review_count") or 0) >= 25:
        hooks.append(f"the {lead['rating']}-star reputation you've earned across {lead['review_count']} reviews")
    hook = " and ".join(hooks) or f"what you've built at {company}"
    subject = f"Quick question about {company}"
    body = (
        f"{greet}\n\n"
        f"I came across {company}{where} and was impressed by {hook}. "
        f"I work with {firm}, where we partner with owner-operators who want their business to keep "
        f"thriving under long-term, hands-on ownership. We're not brokers and there's no pressure.\n\n"
        f"If you've ever wondered what a future transition could look like, I'd welcome a 15-minute "
        f"conversation, entirely confidential and on your timeline.\n\n"
        f"Best,\n{sender}\n{firm}"
    )
    call = (
        f"Hi {owner or 'there'}, this is {sender} from {firm}. I'm not selling anything. I noticed "
        f"{company} has been a fixture{where} for years and wanted to introduce myself, as we partner "
        f"with local owners who care about their legacy. Do you have two minutes?"
    )
    return {"subject": subject, "email": body, "call_opener": call}
