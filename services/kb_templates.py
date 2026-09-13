# -*- coding: utf-8 -*-
"""知识库行业模板：一键生成骨架，客户填 ____ 空位即可。
每套模板覆盖 7 类：公司定位/产品/画像/禁止/报价/口吻/案例。
"""

TEMPLATES = {
    "auto_parts": {
        "label": "Auto parts",
        "desc": "Brake / chassis / filter and other auto-parts export",
        "entries": [
            ("profile", "Company positioning",
             "We are a ____ (auto-parts category) manufacturer/exporter founded in ____, focused on the ____ market. Core strengths: ____ certification (e.g. IATF 16949 / ISO 9001), stable batch dimensions, ____-week lead time for small custom batches. Main customers: European auto-parts importers, distributors and automotive component OEMs."),
            ("product", "Product specifications",
             "Products: ____ series (e.g. brake discs / pads / filters / chassis parts). Parameters: material ____, sizes/models ____, tolerances ____, surface treatment ____, certifications ____ (e.g. ECE R90). MOQ ____ pcs, ____-week lead time for small batches, ____ weeks for volume."),
            ("product", "Delivery & quality commitment",
             "Lead time: small batch (<____ pcs) ____ weeks, volume ____ weeks. Every batch ships with an inspection report (____). Quality issues are replaced or refunded unconditionally."),
            ("guidelines", "Customer profile & strategy",
             "Top priority: ____ in ____ country/region (e.g. auto-parts OEM / importer / distributor), annual purchase value above ____ EUR, value ____ (certification / supply stability / lead time). A = OEM/engineering buyer; B = brand/importer; C = distributor/retailer; D = workshop chain; E = e-commerce/platform. Pain points: ____."),
            ("forbidden", "Forbidden actions",
             "Never promise specs beyond certification scope; never disparage competitors; never claim false stock; never quote customers outside target industries (e.g. ____)."),
            ("pricing", "Pricing strategy",
             "____ EUR per piece (by volume and model); MOQ ____ pcs. Samples ____ (free/paid), freight paid by customer. Payment: TT ____% deposit + ____% before shipment."),
            ("voice", "Language & tone",
             "English emails: concise, engineering tone, let data speak. No exaggerated adjectives, no 'Dear Sir' broadcast templates. Sign off with position and company."),
            ("case_study", "Won deal example",
             "Background: ____ customer's previous supplier ____ (what went wrong). Pain: ____. What we did: ____ (samples / inspection reports / support during testing). Result: ____ (order volume / framework agreement). Takeaway: ____."),
        ],
    },
    "machinery": {
        "label": "Machinery",
        "desc": "CNC machines / processing equipment / production lines export",
        "entries": [
            ("profile", "Company positioning",
             "We are a ____ (equipment category) manufacturer founded in ____, focused on the ____ market. Core strengths: ____ certification, ____, ____ lead time. Main customers: ____ (factories / dealers / OEMs)."),
            ("product", "Equipment specifications",
             "Products: ____ series. Key parameters: working size ____, spindle/power ____, control system ____, applicable materials ____, optional configurations ____, certifications ____, voltage ____. Lead time ____ days/weeks."),
            ("product", "Delivery & service",
             "Lead time: standard model ____ weeks, custom ____ weeks. Includes ____ (installation / training / warranty). Warranty ____ months."),
            ("guidelines", "Customer profile & strategy",
             "Top priority: ____ in ____ country (processing plants / end users / dealers) who care about ____ (efficiency / precision / capacity). A = OEM/plant engineering customer; B = end processing plant; C = equipment dealer; D = maintenance service provider; E = e-commerce/platform. Pain points: ____."),
            ("forbidden", "Forbidden actions",
             "Never promise parameters beyond real performance; never disparage competitors; never claim installed cases we do not have; never quote ____ customers."),
            ("pricing", "Pricing strategy",
             "____ USD per machine (by configuration); MOQ ____ units. Trial/sample ____. Payment: LC/TT ____% deposit."),
            ("voice", "Language & tone",
             "English emails: engineering tone, let parameters and data speak, highlight application cases. Avoid vague promises."),
            ("case_study", "Won deal example",
             "Background: ____ customer needed ____. Pain: ____. Actions: ____ (machine trial / video inspection / customer references). Result: ____. Takeaway: ____."),
        ],
    },
    "electronics": {
        "label": "Electronics",
        "desc": "PCB / connectors / components / consumer electronics export",
        "entries": [
            ("profile", "Company positioning",
             "We are a ____ (electronics category) manufacturer founded in ____, focused on the ____ market. Core strengths: ____ certification (CE/FCC/UL), ____, ____-week prototype runs. Serving ____ customers."),
            ("product", "Product specifications",
             "Products: ____ series. Parameters: layers/size/material/interfaces/specs ____, certifications ____, temperature/humidity range ____. MOQ ____ pcs, prototypes ____ days, mass production ____ weeks."),
            ("product", "Quality & delivery",
             "Lead time: prototypes ____ days, mass production ____ weeks. Every batch ships with test reports (____). Quality issues handled by ____ (rework / replacement / refund)."),
            ("guidelines", "Customer profile & strategy",
             "Top priority: ____ in ____ country (brand owners / EMS / OEMs / distributors) who care about ____ (certification / lead time / price). A = brand owner; B = EMS/OEM; C = distributor; D = solution provider; E = e-commerce seller. Pain points: ____."),
            ("forbidden", "Forbidden actions",
             "Never promise beyond certification scope; never fabricate test data; never quote ____ customers."),
            ("pricing", "Pricing strategy",
             "____ USD per pcs (by volume); MOQ ____; prototype fee ____ (refundable). Payment: TT ____%."),
            ("voice", "Language & tone",
             "English emails: concise, let technical parameters speak, highlight certifications and test reports."),
            ("case_study", "Won deal example",
             "Background: ____ customer needed ____. Pain: ____. Actions: ____ (prototype / certification / testing). Result: ____. Takeaway: ____."),
        ],
    },
    "hardware": {
        "label": "Hardware",
        "desc": "Fasteners / stampings / door & window hardware / tools export",
        "entries": [
            ("profile", "Company positioning",
             "We are a ____ (hardware category) manufacturer/exporter founded in ____, focused on the ____ market. Core strengths: ____, full range of materials and surface finishes, flexible MOQ. Serving ____ customers."),
            ("product", "Product specifications",
             "Products: ____ series. Parameters: material ____ (carbon steel / stainless steel / aluminum), size range ____, tolerances ____, surface treatment ____ (zinc / anodized / e-coat). MOQ ____, lead time ____ weeks."),
            ("product", "Quality & packaging",
             "Lead time: standard ____ weeks, custom ____ weeks. Every batch ships with material certificates. Export packaging: ____."),
            ("guidelines", "Customer profile & strategy",
             "Top priority: ____ in ____ country (OEM supply / hardware wholesalers / cross-border e-commerce) who care about ____ (price / lead time / certification). A = OEM supply; B = hardware wholesaler; C = retail chain; D = e-commerce seller; E = project/engineering buyer. Pain points: ____."),
            ("forbidden", "Forbidden actions",
             "Never misstate material grades; never promise salt-spray tests that cannot pass; never quote ____ customers."),
            ("pricing", "Pricing strategy",
             "____ USD per piece (by volume or per kg); MOQ ____; samples ____. Payment: TT ____%."),
            ("voice", "Language & tone",
             "English emails: direct, checklist style, highlight specs and certifications."),
            ("case_study", "Won deal example",
             "Background: ____ customer needed ____. Pain: ____. Actions: ____ (samples / tooling / certification). Result: ____. Takeaway: ____."),
        ],
    },
    "general": {
        "label": "General",
        "desc": "Industry-neutral starter skeleton",
        "entries": [
            ("profile", "Company positioning",
             "We are a ____ (product category) manufacturer/exporter founded in ____, focused on the ____ market. Core strengths: ____ certification, ____, ____ lead time. Main customers: ____."),
            ("product", "Product specifications",
             "Products: ____ series. Parameter range: ____. Certifications: ____. MOQ ____, small-batch lead time ____ weeks, volume ____ weeks."),
            ("product", "Delivery & quality commitment",
             "Lead time: small batch ____ weeks, volume ____ weeks. Every batch ships with ____ reports. Quality issues: ____."),
            ("guidelines", "Customer profile & strategy",
             "Top priority: ____ customers in ____ country, annual purchase value ____, value ____. A = ____; B = ____; C = ____; D = ____; E = ____. Pain points: ____."),
            ("forbidden", "Forbidden actions",
             "Never promise specs beyond real capability; never disparage competitors; never claim false stock; never quote ____ customers."),
            ("pricing", "Pricing strategy",
             "____ quote (by volume); MOQ ____; samples ____; payment ____."),
            ("voice", "Language & tone",
             "English emails: concise, professional, data-driven. No 'Dear Sir' broadcast templates."),
            ("case_study", "Won deal example",
             "Background: ____ customer's previous supplier ____. Pain: ____. Actions: ____. Result: ____. Takeaway: ____."),
        ],
    },
}


def list_templates() -> list:
    return [
        {"key": k, "label": v["label"], "desc": v["desc"]}
        for k, v in TEMPLATES.items()
    ]


def get_template(key: str):
    return TEMPLATES.get(key)
