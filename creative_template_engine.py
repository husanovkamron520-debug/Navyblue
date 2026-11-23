"""Curated starter selection for October Creative Builder."""
from __future__ import annotations

TEMPLATES = {
    "cosmos_3d": {"title": "Cinematic 3D kosmos — Deep Space & Orbital Simulation", "keywords": ("sayyora", "sayyoralar", "planet", "kosmos", "galaktika", "space"), "layout": "NASA/IMAX-grade deep-space observatory: one dominant gas giant or ocean-cloud exoplanet, one or two moons, layered volumetric-looking nebula, deep parallax starfield and an equatorial orbital asteroid belt", "must_have": ("high-resolution procedural CanvasTexture with storms, gas bands or craters plus bumpMap/normalMap relief", "Fresnel ShaderMaterial atmosphere with sun-facing blue or gold rim", "DirectionalLight sun plus central PointLight and day/night terminator", "EffectComposer + RenderPass + UnrealBloomPass with graceful base-render fallback", "400–600 irregular rocks rendered using THREE.InstancedMesh", "OrbitControls with enableDamping and dampingFactor 0.04", "slow automatic orbital camera motion without fighting manual input", "three camera presets: planet orbit, asteroid belt and wide panorama, smoothly interpolated with Vector3.lerp/lerpVectors", "no visible HUD, labels, text, tooltips, legends, object descriptions or numeric metrics; pure visual scene only", "planet selection via raycasting and smooth camera fly-to", "layered ShaderMaterial nebula and parallax starfield", "conditional ring shadows and optional moon eclipse", "mobile adaptive quality, capped pixel ratio and asteroid/bloom budgets", "visible loading progress and recoverable WebGL/import error state")},
    "room_3d": {
        "title": "3D xona/interyer — Architectural Interior & Smart Living",
        "keywords": ("xona", "interyer", "mebel", "stol", "divan", "yotoqxona", "room", "interior", "penthouse", "studio"),
        "layout": "premium minimalist studio or penthouse architectural visualization, open-front L-shaped two-wall room shell with a continuous floor, realistic scale, carefully composed furniture and warm modern styling",
        "must_have": (
            "open-front architectural shell made from exactly two visible perpendicular walls and a floor; never place a front wall across the camera",
            "rounded furniture silhouettes using THREE.RoundedBoxGeometry or a custom rounded-box geometry; avoid sharp default BoxGeometry furniture",
            "central modular sofa built from separate base, seat cushions, backrest and small decorative cushions",
            "woven fabric rug in front of the sofa with a visible procedural woven texture",
            "transparent glass coffee table with slim metallic legs, plus a small book and cup",
            "back wall vertical wood slats with concealed warm LED strip lighting",
            "large wall-mounted screen with a live dynamic canvas visualization, not a static blank rectangle",
            "tall indoor plant in a corner and a curved modern floor lamp",
            "RoomEnvironment and PMREMGenerator-generated environment map for convincing glass, metal and polished-floor reflections",
            "soft angled daylight from a side window, physically plausible contact shadows, PCFSoftShadowMap and 2048x2048 shadow maps",
            "hidden ceiling cove lighting; no visible ceiling slab blocking the camera",
            "two smooth lighting moods: Daylight and Night Neon / Evening Cozy, with animated transitions for light intensity, color and environment",
            "three working camera presets: Sofa view, TV / desk view and Top-down plan, smoothly interpolated",
            "realistic ArchViz materials, roughness variation, ambient occlusion-like depth, soft shadows and balanced exposure",
            "mobile adaptive quality, capped pixel ratio, responsive canvas and touch-friendly camera controls",
            "recoverable WebGL/import error state and a visible loading state"
        )
    },
    "warehouse_3d": {
        "title": "3D ombor/zavod — Smart Warehouse & Logistics Twin",
        "keywords": ("ombor", "warehouse", "zavod", "factory", "pallet", "stellaj", "logistika", "forklift", "loading dock", "wms"),
        "layout": "a premium industrial digital twin of a modern automated distribution center, with a broad epoxy-concrete floor, six long multi-level rack aisles, loading docks and a clearly readable central material-flow route",
        "must_have": (
            "large smooth industrial epoxy/concrete floor with a procedural CanvasTexture, yellow safety lines, pedestrian crossing and clearly painted ZONE A, ZONE B and DOCK 01 markings",
            "four to six long multi-level steel pallet-rack rows with blue or grey uprights and safety-orange beams",
            "hundreds of varied cardboard cartons and wooden pallets distributed across rack bays using THREE.InstancedMesh for repeated geometry",
            "distinct loading dock doors along one side, with a parked delivery truck or trailer at a dock",
            "a continuously moving forklift following a defined aisle route, or a working animated conveyor line; avoid collisions with racks",
            "suspended industrial LED fixtures and clean neutral grey-blue lighting using HemisphereLight and DirectionalLight",
            "clickable rack rows selected with THREE.Raycaster, with clear visual highlighting and a right-side WMS information panel",
            "WMS sample fields for selected rack: zone/row name, capacity percentage, active SKU count and temperature in Celsius; clearly simulated demo data",
            "three working camera presets: Top-Down bird's-eye, Aisle Walkthrough and Loading Dock",
            "mobile-adaptive rendering, capped pixel ratio, reduced instance/shadow budget on smaller devices and touch-friendly controls",
            "visible loading progress and recoverable WebGL/import error state"
        )
    },
    "birthday_gallery": {"title": "Tug‘ilgan kun va foto-galereya", "keywords": ("tug'ilgan", "tugilgan", "birthday", "tabrik", "surat", "rasm", "photo", "gallery"), "layout": "warm celebratory hero, elegant typography, photo-led composition and restrained motion", "must_have": ("uploaded photos displayed directly", "mobile-friendly layout", "working interactions", "reduced-motion support")},
    "portfolio": {"title": "Portfolio va biznes sayti", "keywords": ("portfolio", "biznes", "business", "landing", "sayt", "website", "agency", "company"), "layout": "strong hero, clear navigation, proof/services section and concise CTA", "must_have": ("responsive navigation", "working CTA links", "semantic sections", "accessible contrast")},
    "dashboard": {"title": "Dashboard va interaktiv panel", "keywords": ("dashboard", "panel", "statistika", "grafik", "chart", "monitoring", "analytics", "admin"), "layout": "calm dashboard, KPI cards, chart area, filters and responsive navigation", "must_have": ("meaningful sample data", "working filters", "readable chart labels", "mobile layout")},
    "general": {"title": "Universal responsive HTML", "keywords": (), "layout": "clear hierarchy, balanced whitespace, consistent component styling and mobile-first layout", "must_have": ("semantic HTML", "responsive layout", "working controls", "accessible text contrast")},
}

def select_template(request: str):
    text = (request or "").casefold()
    scored = [(sum(1 for word in item["keywords"] if word.casefold() in text), key) for key, item in TEMPLATES.items()]
    scored = [entry for entry in scored if entry[0]]
    if not scored:
        return "general", TEMPLATES["general"]
    _, key = max(scored, key=lambda pair: (pair[0], pair[1]))
    return key, TEMPLATES[key]

def template_prompt(request: str) -> str:
    key, item = select_template(request)
    cinematic_note = (
        "COSMOS CINEMATIC OVERRIDE: treat the Deep Space & Orbital Simulation specification as a hard acceptance checklist. Implement the exact 400–600 InstancedMesh asteroid range, dampingFactor 0.04, three camera presets with smooth lerp transitions, procedural surface relief, Fresnel rim, layered nebula and bloom fallback as working code. Absolutely no HUD, scientific values, object information, labels, tooltips, legends, instructions or any visible screen text; never replace the pure visual scene with static screenshots or decorative labels.\\n"
        if key == "cosmos_3d" else ""
    )
    room_note = (
        "ARCHVIZ ROOM OVERRIDE: this is a premium architectural visualization, not a primitive box room. "
        "Build an open-front L-shaped room from two perpendicular walls and a floor; keep the camera side completely open. "
        "Use rounded furniture geometry (THREE.RoundedBoxGeometry from three/addons/geometries/RoundedBoxGeometry.js or a robust custom rounded-box helper), "
        "never sharp BoxGeometry for furniture. Build a modular sofa from distinct base, seat cushions, backrest and small throw cushions. "
        "Add a woven rug with procedural canvas fabric texture, a transparent glass coffee table with slim metal legs, a book and a cup. "
        "The rear wall must have vertical wood slats, concealed warm LED strips and a large screen whose content is drawn dynamically on canvas. "
        "Add a tall corner plant and a curved modern floor lamp. Use RoomEnvironment + PMREMGenerator to create the scene environment map "
        "and apply it to glass, metal and polished floor materials. Add angled soft daylight from a side window, PCFSoftShadowMap, "
        "2048x2048 shadow maps, contact shadows and hidden ceiling cove lights; do not add a ceiling slab that blocks the view. "
        "Implement two real lighting presets named Daylight and Night Neon / Evening Cozy with smooth interpolated changes to light color, "
        "intensity and background/environment. Implement three camera presets named Sofa view, TV / desk and Top-down plan with smooth transitions. "
        "Prioritize photorealistic ArchViz material response, roughness variation, realistic scale and mobile adaptive quality. "
        "All presets and lighting switches must work, not be decorative buttons.\\n"
        if key == "room_3d" else ""
    )
    warehouse_note = (
        "SMART WAREHOUSE DIGITAL TWIN OVERRIDE: create an industrial-grade, visually rich warehouse simulation, not a toy room or a few floating cubes. "
        "Use a large concrete/epoxy floor with a procedural CanvasTexture that visibly includes yellow safety boundaries, pedestrian zebra crossing, "
        "ZONE A, ZONE B and DOCK 01 floor paint. Build four to six long parallel steel rack rows, each with multiple storage levels, blue/grey vertical "
        "uprights and orange horizontal beams. Populate rack bays densely but legibly with hundreds of differently sized and colored carton boxes and "
        "wooden pallets; use THREE.InstancedMesh for repeated cartons/pallets and deterministic placement so they sit correctly inside rack bays. "
        "At one side create realistic loading dock doors, dock bumpers/levelers and a delivery truck or trailer. In the central aisle animate a forklift "
        "continuously along a closed, clearly marked route at a safe speed, or build a moving conveyor; it must not clip through racks or the floor. "
        "Suspend rows of industrial LED fixtures below the roof structure and light with HemisphereLight + DirectionalLight in a neutral grey-blue palette. "
        "Create a right-side WMS HUD panel. Use THREE.Raycaster on pointer/touch input to select an entire rack row; highlight the selected row with a "
        "subtle emissive/outline treatment and update the panel with zone/row, capacity %, active SKU count and temperature. Use coherent, explicitly "
        "simulated sample values such as Zona A-2 | Sig'im: 88% | Aktiv SKU: 420 ta | Harorat: +18°C; values should vary by selected row and remain stable "
        "between selections. Implement three real camera presets: Top-Down bird's-eye, Aisle Walkthrough and Loading Dock, smoothly interpolating camera "
        "position and OrbitControls target. All controls must work, selected rack must be visually obvious, and the WMS panel must remain readable without "
        "covering the 3D scene. Add responsive mobile layout, capped DPR, lower instance/shadow budgets on phones, resize handling, loading state and "
        "recoverable WebGL/import errors. Never substitute a static image for the interactive Three.js scene.\\n"
        if key == "warehouse_3d" else ""
    )
    return ("TANLANGAN STARTER: " + item["title"] + " (ID: " + key + ").\\n"
            "Vizual tuzilma: " + item["layout"] + ".\\n"
            "Majburiy sifat mezonlari: " + "; ".join(item["must_have"]) + ".\\n"
            + cinematic_note + room_note + warehouse_note +
            "Bu tayyor dizayn yo'nalishi, foydalanuvchi so'rovining o'rnini bosmaydi. "
            "So'rovdagi rang, obyekt, matn, rasm va joylashuv ko'rsatmalarini birinchi o'ringa qo'y. "
            "Shablonni mazmun va kompozitsiya bo'yicha vazifaga moslashtir.")
