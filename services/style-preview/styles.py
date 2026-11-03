"""The tailor's starting catalog. Descriptions go into the Muse Image prompt, so they describe the
cut only (not colour or pattern, which come from the customer's fabric). Tailors can add styles here;
each one also needs a pattern in services/fabric-calculator/calculator.py (pieces, ease, finished sizes).

`group` is only for the style picker: who the style is usually made for.
"""

CATALOG = {
    # ---- usually for men ----
    "agbada": {
        "name": "Agbada",
        "group": "Men",
        "description": "a Nigerian agbada: a very wide, flowing, ankle-length outer robe with open sides that drape over the arms and an embroidered neckline, worn over a long-sleeved inner tunic and straight trousers",
    },
    "senator": {
        "name": "Senator",
        "group": "Men",
        "description": "a Nigerian senator outfit: a long-sleeved, hip-length tunic with a mandarin collar and a plain front placket, worn with straight full-length trousers",
    },
    "kaftan": {
        "name": "Kaftan",
        "group": "Men",
        "description": "a Nigerian kaftan: a loose, long, ankle-length robe-style top with wide sleeves and a simple round neckline, worn over matching trousers",
    },
    "buba_sokoto": {
        "name": "Buba and sokoto",
        "group": "Men",
        "description": "a Yoruba buba and sokoto: a loose, long-sleeved, below-hip-length pullover top with a round neckline, worn with loose, roomy trousers gathered at the waist",
    },
    # ---- usually for women ----
    "gown": {
        "name": "Gown",
        "group": "Women",
        "description": "a floor-length gown with a fitted bodice and a gently flared skirt",
    },
    "mermaid_gown": {
        "name": "Mermaid gown",
        "group": "Women",
        "description": "a floor-length mermaid gown: fitted through the bust, waist and hips down to the knee, then flaring out in a full fishtail skirt",
    },
    "iro_buba": {
        "name": "Iro and buba",
        "group": "Women",
        "description": "an iro and buba: a loose-fitting buba blouse with wide sleeves and an iro wrapper skirt tied at the waist, ankle length",
    },
    "bubu": {
        "name": "Bubu (boubou)",
        "group": "Women",
        "description": "a bubu (boubou): a very loose, flowing, floor-length kaftan dress with wide batwing sleeves and a round or V neckline",
    },
    "skirt_blouse": {
        "name": "Skirt and blouse",
        "group": "Women",
        "description": "a fitted long-sleeved blouse with a round neckline, worn with a fitted, ankle-length pencil skirt",
    },
    "jumpsuit": {
        "name": "Jumpsuit",
        "group": "Women",
        "description": "a long-sleeved jumpsuit with a fitted bodice and straight, full-length trouser legs, cinched at the waist",
    },
    # ---- for anyone ----
    "dashiki": {
        "name": "Dashiki",
        "group": "Anyone",
        "description": "a dashiki: a loose, hip-length pullover top with short wide sleeves and a V or round neckline with a decorated yoke",
    },
    "shirt": {
        "name": "Long-sleeved shirt",
        "group": "Anyone",
        "description": "a tailored long-sleeved shirt with a pointed collar, a buttoned front and buttoned cuffs, hip length",
    },
    "trousers": {
        "name": "Trousers",
        "group": "Anyone",
        "description": "straight, full-length tailored trousers with a waistband and side pockets",
    },
}
GROUPS = ("Men", "Women", "Anyone")
