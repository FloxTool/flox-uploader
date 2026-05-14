# Charte graphique — Flox Uploader

> Version : 0.3.0 · Sprint round 8-9
> Source unique de vérité pour le design system. Quand on ajoute un composant,
> il doit respecter cette charte — pas s'en écarter par confort.

Inspirations : Linear, Vercel, Arc, Notion, Things 3.

---

## 1. Palette

### Couleurs sémantiques

Toutes définies dans `base.html` via `tailwind.config.theme.extend.colors`. Toujours
préférer les tokens aux hex directs.

| Token | Light base (500) | Usage |
|---|---|---|
| **primary** | `#6366f1` (indigo-500) | CTA, liens, focus, accent de marque |
| **success** | `#10b981` (emerald-500) | États positifs (uploaded, prêt, validé) |
| **warning** | `#f59e0b` (amber-500) | Attention non-bloquante, doublon probable |
| **danger** | `#ef4444` (red-500) | Erreurs, doublon certain, actions destructives |
| **neutral** | `slate-*` | Texte, bordures, backgrounds (jamais "gray", toujours "slate") |

Chaque couleur a 11 paliers (50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950).
Convention d'usage :

- **50** : background très clair (alert subtil, hover)
- **100-200** : background (cartes, panels), bordures discrètes
- **300-400** : bordures prominentes, disabled
- **500** : couleur de marque, base
- **600** : texte sur fond clair, fill icônes
- **700** : texte plus contrasté, hover-states clairs
- **800-900-950** : dark mode backgrounds

### Variables CSS (design tokens)

Définies dans `:root` (light) et `html.dark` (dark) dans `base.html` :

```css
--tu-primary: 99, 102, 241;        /* indigo-500 RGB, pour rgba() */
--tu-ease: cubic-bezier(0.16, 1, 0.3, 1);
--tu-fast: 180ms;
--tu-base: 240ms;
--tu-press: 80ms;
--tu-border-subtle: …               /* slate-100 / slate-700-60 */
--tu-border-prominent: …            /* slate-200 / slate-700 */
```

### Dark mode

Tous les composants supportent obligatoirement light + dark via les variantes
`dark:` de Tailwind. La règle :

- Background body → `bg-slate-100 dark:bg-slate-950`
- Background card → `bg-white dark:bg-slate-800`
- Bordure subtile → `border-slate-100 dark:border-slate-700/60`
- Bordure prominente → `border-slate-200 dark:border-slate-700`
- Texte principal → `text-slate-900 dark:text-slate-100`
- Texte secondaire → `text-slate-600 dark:text-slate-400`
- Texte tertiaire → `text-slate-500 dark:text-slate-400`

Le mode dark est appliqué via la classe `dark` sur `<html>`. Init précoce dans
`base.html` (avant Tailwind CDN) pour éviter le flash blanc au boot.

---

## 2. Typographie

### Familles

```css
sans: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif
mono: '"JetBrains Mono"', '"SF Mono"', Consolas, Menlo, monospace
```

Inter en **variable font** (`wght@100..900`) — un seul fichier, tous les poids
disponibles. Chargé via Google Fonts avec `display=swap`.

### Tailles + line-height

Échelle Tailwind par défaut (text-xs à text-3xl). Usage canonique :

| Classe | Pixels | Usage |
|---|---|---|
| `text-[10px]` | 10 | Labels uppercase, kbd, chips compacts |
| `text-[11px]` | 11 | Métadonnées secondaires |
| `text-xs` | 12 | Body dense (tables, tooltips), helper text |
| `text-sm` | 14 | Body courant (paragraphes, descriptions, labels) |
| `text-base` | 16 | Body emphase (titres de cards) |
| `text-lg` | 18 | H2 de section |
| `text-2xl` | 24 | H1 de page detail |
| `text-3xl` | 30 | Hero (guide, setup) |

### Letter-spacing

Pour le look premium "Linear/Vercel", on serre les titres (NOTES round 8 P4.5) :

```css
h1 { letter-spacing: -0.025em; }
h2 { letter-spacing: -0.015em; }
/* h3+ et body restent en default */
```

### Font features

```css
body {
    font-feature-settings: 'cv02', 'cv03', 'cv04', 'cv11';
}
/* tabular-nums automatique sur tous les contextes numériques alignés : */
tbody td, kbd, .tu-num, .tabular-nums, [data-tu-num] {
    font-variant-numeric: tabular-nums;
}
```

### Police mono

Réservée à : release names, paths, code inline, kbd contents, sortie console/log.

---

## 3. Échelle d'espacement (4px-grid)

Tailwind valeurs autorisées, dans cet ordre de priorité :

| Valeur | Pixels | Usage canonique |
|---|---|---|
| `0.5` | 2 | Très tight — badge interne, icon adjacent texte |
| `1` | 4 | Tight — chip gap, micro-padding |
| `1.5` | 6 | Moyen-tight — icon + label dans bouton sm |
| `2` | 8 | Normal — gap standard between items |
| `2.5` | 10 | Table cell — densité confortable mais compacte |
| `3` | 12 | Large — padding horizontal de card |
| `3.5` | 14 | Button med — padding x bouton md |
| `4` | 16 | Section gap — entre cartes/sections |
| `5` | 20 | Button lg — padding x bouton lg |
| `6` | 24 | Large gap — page header sep |
| `8` | 32 | Extra-large |

**À éviter** : 7, 9, 10, 11, 13, 14, 15. Si un cas particulier exige une autre
valeur, mettre un commentaire qui justifie.

---

## 4. Bordures + radius + ombres

### Bordures (2 niveaux)

- `--tu-border-subtle` (slate-100 / slate-700/60) → 80% des cas (séparateurs)
- `--tu-border-prominent` (slate-200 / slate-700) → contraste plus marqué

### Radius

| Classe | Valeur | Usage |
|---|---|---|
| `rounded` | 4px | Inputs, kbd, badges très compacts |
| `rounded-md` | 6px | Boutons, chips, dropdowns items |
| `rounded-lg` | 8px | Cards, popovers, toasts |
| `rounded-xl` | 12px | Modals (dialog), command palette |
| `rounded-full` | ∞ | Badges position (job #1), icons rondes |

Le `border-radius` est respecté par les focus rings grâce au `outline + outline-offset`
plutôt que `box-shadow` (cf. section Focus).

### Ombres (custom Tailwind)

```js
xs:    '0 1px 2px rgba(0,0,0,0.05)'
sm:    '0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.04)'
md:    '0 4px 6px -1px rgba(0,0,0,0.10), 0 2px 4px -2px rgba(0,0,0,0.06)'
lg:    '0 10px 15px -3px rgba(0,0,0,0.12), 0 4px 6px -4px rgba(0,0,0,0.05)'
focus: '0 0 0 3px rgba(99,102,241,0.4)'
```

Usage : `shadow-sm` sur cards, `shadow-md` sur popovers, `shadow-lg` sur modals.

---

## 5. Transitions + easing

### Durations

```js
duration-fast:  180ms   /* interactions standard (hover, color change) */
duration-base:  240ms   /* transitions structurelles (modals, popovers) */
duration-slow:  320ms   /* enter/exit majeurs */
```

Plus 80ms (`--tu-press`) pour le feedback "press" (active state).

### Easing

```js
ease-tu: cubic-bezier(0.16, 1, 0.3, 1)
```

C'est l'easing "smooth spring" inspiré Linear/Vercel. Démarre vite, finit doux —
sensation naturelle (vs `ease-out` classique trop sec). À utiliser via la classe
Tailwind `ease-tu` ou via la var CSS `var(--tu-ease)`.

### Reduced motion

```css
@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.01ms !important;
    }
}
```

---

## 6. Focus + feedback haptique

### Focus visible (uniforme tout l'app)

```css
:focus-visible {
    outline: 2px solid rgba(var(--tu-primary), 0.85);
    outline-offset: 2px;
    transition: outline-offset 80ms var(--tu-ease);
}
:focus:not(:focus-visible) { outline: none; }
```

L'outline hérite naturellement du border-radius parent (contrairement à box-shadow
qui imposait un radius fixe). Le focus apparaît uniquement au Tab clavier, jamais
au click souris.

### Classe `.interactive` (à appliquer sur tout bouton / chip / lien clickable)

```css
.interactive {
    transition:
        background-color var(--tu-fast) var(--tu-ease),
        border-color var(--tu-fast) var(--tu-ease),
        color var(--tu-fast) var(--tu-ease),
        opacity var(--tu-fast) var(--tu-ease),
        box-shadow var(--tu-fast) var(--tu-ease),
        transform var(--tu-press) var(--tu-ease);
}
.interactive:active:not(:disabled) {
    transform: scale(0.97);                 /* feedback "press" */
}
.interactive:disabled,
.interactive[aria-disabled="true"] {
    cursor: not-allowed;
    opacity: 0.5;
}
```

Automatiquement appliquée par les macros `button()` et `link_button()` dans
`_components.html`.

---

## 7. Z-index ladder

**Ne JAMAIS dépasser 80** (sinon les tooltips passent en-dessous).

| Z | Élément |
|---|---|
| 80 | Tooltips (`.tu-tooltip`) |
| 70 | Toast container |
| 60 | Command palette (`#cmdk-root`) |
| 55 | Modal (`#modal-root`, log-modal, bundle-modal) |
| 50 | Page loader |
| 40 | Mobile topbar, sidebar |
| 30 | Sidebar backdrop, dropdowns |
| 20 | Sticky toolbars |
| 10 | Sticky page chrome |

---

## 8. Composants (`templates/_components.html`)

### Button macro

```jinja
{{ button(label, variant, size, icon_name, icon_position, icon_only,
          disabled, loading, tooltip, tooltip_kbd, id, name, value,
          attrs, extra_classes) }}
```

**Variants** : `primary` (CTA), `secondary` (action secondaire bordée), `ghost`
(discret hover), `danger`, `danger-soft`, `success`, `success-soft`,
`warning`, `warning-soft`.

**Sizes** : `sm` (h-7 = 28px), `md` (h-9 = 36px, default), `lg` (h-11 = 44px).

`icon_only=True` rend un bouton carré. `loading=True` swap l'icône pour un spinner
inline + ajoute `aria-busy="true"`. `tooltip="…"` baked-in via data-tu-tooltip.

### Badge macro

```jinja
{{ badge(label, tone, icon_name, size) }}
```

**Tones** : `neutral`, `primary`, `success`, `warning`, `danger`, `info`.
**Sizes** : `sm`, `md` (default).

Toujours rendu avec `ring-1 ring-inset ring-{tone}-200` pour une bordure interne
sans déborder du flux.

### Card macro (avec `{% call %}`)

```jinja
{% call card(title='…', subtitle='…', action=button(…)) %}
    <p>contenu</p>
{% endcall %}
```

### Empty state

```jinja
{{ empty_state(title, description, icon_name, action_label, action_href,
               secondary_label, secondary_href) }}
```

Icône 64px dans un cercle slate, h3 titre, paragraphe description, CTA bouton
primary + lien secondaire optionnel.

### Input text

```jinja
{{ input_text(name, label, value, placeholder, kind, id, disabled,
              helper, error, attrs) }}
```

Helper text en gris si pas d'erreur, sinon erreur en danger-600.

### Link button

API identique à `button()` mais rend un `<a href>`. Mêmes variants/sizes.

### Logo

Le logo Flox Uploader vit dans **deux représentations** :

1. **Fichier statique** `src/flox_uploader/web/static/logo.svg`
   - Utilisé par `<img src="/static/logo.svg">`, `<link rel="icon">`, PWA, OG image
   - Couleur par défaut **`#6366f1`** (charte) via `style="color: …"` sur la racine
   - Le `<img>` étant un document isolé, **ne s'adapte pas au CSS parent**
   - Paths en `fill="currentColor"` (prêt pour inlining si besoin)

2. **Macro Jinja `logo()`** dans `_components.html`
   - Inline le SVG dans le HTML → hérite du CSS `color:` du parent
   - Usage : `{{ logo() }}` → indigo, `{{ logo(classes='w-9 h-9 text-white') }}` → blanc, etc.
   - Préféré quand on veut un logo qui suit le theme (light/dark, fond foncé/clair)

**Quand utiliser quoi ?**
- `<img src="/static/logo.svg">` → favicon, PWA, OG, partage social, contexte
  externe à l'app (le SVG est rendu standalone, currentColor ne s'applique pas)
- `{{ logo() }}` → header, sidebar, hero d'une page, partout dans le rendu HTML
  où on veut une couleur qui colle au thème

**Fichier source** : `assets/img/logo.svg` (master export Illustrator, ne pas
référencer depuis le code applicatif). Sert d'archive avant nettoyage.

#### Export Illustrator propre (pour les futures versions)

Quand tu refais le logo depuis Illustrator (refresh, variante…), exporte de
cette manière pour minimiser le nettoyage manuel ensuite :

1. **Sélectionne uniquement l'artwork** (pas d'arrière-plan blanc Illustrator)
2. `Fichier > Exporter > Exporter sous` → format **SVG**
3. Dans la boîte de dialogue SVG Options :
   - **Styling** : `Internal CSS` ou `Presentation Attributes` (présentation est mieux pour notre cas, mais interne marche aussi — on clean tout de toute façon)
   - **Font** : `Convert to outlines` (si le logo a du texte)
   - **Images** : `Embed` (si jamais)
   - **Object IDs** : `Minimal` (pas Layer Names)
   - **Decimal** : `1` ou `2` (assez précis, pas verbeux)
   - **Minify** : `coché` (retire whitespace inutile)
   - **Responsive** : `coché` (retire `width`/`height` fixes)
4. Verifie le viewBox dans le fichier : doit englober pile l'artwork, pas plus
5. Envoie-moi le fichier → je clean les dernières miettes (`<defs>`, IDs, etc.)

Cruft typique d'Illustrator à nettoyer (que je gère automatiquement) :
- `<?xml version=…?>` (inutile pour SVG inline)
- `id="Layer_1"` `data-name="Layer 1"`
- `<defs><style>.cls-N { fill: #xxx }</style></defs>` → fill direct sur path
- Commentaires Illustrator (`<!-- Generator: Adobe Illustrator -->`)

---

## 9. Iconographie

### Bibliothèque

[Lucide](https://lucide.dev/) — inline SVG via `_icons.html`. Toutes les
icônes utilisées sont copiées dans la map du macro `icon()`.

```jinja
{{ icon(name, size='md', classes='') }}
```

**Sizes** : `sm` (14px), `md` (16px, default), `lg` (20px), `xl` (24px).

### Règles

- **Pas d'emoji dans l'UI** — toujours une icône Lucide.
- Si une icône manque, l'ajouter dans `_icons.html` (pas inline ailleurs).
- Couleur via `currentColor` (hérite du parent) — pas de fill hardcodé.
- `stroke-width: 2`, `stroke-linecap: round`, `stroke-linejoin: round` (uniformisé).

### Exception : drapeaux

Pour les langues/régions (FR, US, JA, etc.), on utilise les emojis Unicode
🇫🇷 🇺🇸 🇯🇵 etc., remplacés à l'exécution par Twemoji (SVG colorés universels)
via `tuParseEmoji(document.body)`.

---

## 10. Patterns UX

### Tooltip (`window.tu` + `data-tu-tooltip`)

```html
<button data-tu-tooltip="Description utile">…</button>
<button data-tu-tooltip="Ouvrir la recherche"
        data-tu-tooltip-kbd="⌘K">…</button>
```

- Show delay : 220ms (hover) / 0ms (focus clavier)
- Hide delay : 80ms
- Animation : 100ms opacity / 160ms translate
- Flèche pointée vers le trigger (rotate 45°, flip auto)
- ARIA : `role="tooltip"` + `aria-describedby` auto sur le trigger
- Echap ferme tout tooltip ouvert
- Support `<kbd>` inline pour raccourcis (XSS-safe : pas d'HTML brut accepté)

### Toast (`tu.toast({title, message, tone, duration})`)

- Top-right, animation slide-in 180ms
- **Tones** : `info`, `success`, `warning`, `danger`
- Auto-dismiss après `duration` ms (default 4000), `0` = manuel
- Bouton close intégré
- ARIA `role="status"`, container `aria-live="polite"`

### Confirm modal (`tu.confirm({title, message, tone, …}) → Promise<bool>`)

```javascript
const ok = await tu.confirm({
    title: 'Supprimer ?',
    message: 'Action irreversible.',
    confirmLabel: 'Supprimer',
    tone: 'danger',
});
if (!ok) return;
```

- Focus initial : `confirm` button si tone neutre, `cancel` button si tone
  `danger` ou `warning` (anti-accident).
- Enter → confirm (sauf si focus sur cancel : Enter → cancel).
- Escape → cancel.
- Backdrop click → cancel.

### Async button (`tu.button(el, asyncFn, options)`)

```javascript
btn.addEventListener('click', () => tu.button(btn, async () => {
    const r = await fetch(url, {method: 'POST'});
    if (!r.ok) throw new Error('failed');
    tu.toast({title: 'OK', tone: 'success'});
}));
```

- Pendant l'exécution : icône remplacée par spinner, `disabled`, `aria-busy="true"`.
- Toast d'erreur automatique si la promise reject (sauf `onError` custom).

### Skeleton loader

```html
<div class="tu-skeleton h-4 w-32"></div>
```

Animation shimmer 1.6s ease-in-out infinite. Combine avec utilities Tailwind pour
la taille.

### Command palette (Cmd+K / Ctrl+K)

- Recherche fuzzy sur pages + actions + packages
- Navigation clavier (↑/↓ navigate, Enter activate, Esc close)
- Au premier load, badge ⌘K dans la sidebar pulse subtilement jusqu'à la 1ère
  utilisation (flag `tu_cmdk_used` en localStorage).

### Search input clear button

Tous les champs `.tu-search-input` dans un wrapper `.tu-search-wrap` reçoivent
automatiquement un bouton `×` à droite qui :
- Apparaît dès qu'il y a du contenu, disparaît si vide
- Clear + focus l'input + dispatch un événement `input` (les filtres se re-runnent)
- Escape clear aussi le champ

---

## 11. Animations spécifiques

### Modal pop-in

```css
@keyframes modal-in {
    from { opacity: 0; transform: scale(0.96); }
    to   { opacity: 1; transform: scale(1); }
}
.modal-dialog { animation: modal-in 160ms ease-out; }
```

### Toast slide

```css
@keyframes toast-in {
    from { transform: translateX(110%); opacity: 0; }
    to   { transform: translateX(0); opacity: 1; }
}
.toast { animation: toast-in 180ms ease-out; }
```

### Score glow (parfait/quasi-parfait)

```css
.score-glow-parfait {
    box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.5),
                0 0 12px 0 rgba(16, 185, 129, 0.25);
}
.score-glow-perfect {
    box-shadow: 0 0 0 1px rgba(16, 185, 129, 0.35);
}
```

### Checkbox flash

```css
@keyframes tu-checkbox-flash {
    0%   { box-shadow: 0 0 0 0 rgba(var(--tu-primary), 0.35); }
    60%  { box-shadow: 0 0 0 6px rgba(var(--tu-primary), 0); }
    100% { box-shadow: 0 0 0 0 rgba(var(--tu-primary), 0); }
}
```

Déclenché automatiquement au click sur n'importe quelle checkbox (handler global).

---

## 12. Scrollbar

```css
::-webkit-scrollbar { width: 7px; height: 7px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb {
    background-color: rgba(148, 163, 184, 0.35);
    border-radius: 4px;
    background-clip: padding-box;
    border: 1px solid transparent;
}
::-webkit-scrollbar-thumb:hover { background-color: rgba(148, 163, 184, 0.55); }
* { scrollbar-width: thin; scrollbar-color: rgba(148, 163, 184, 0.35) transparent; }
```

Style Linear : fine (7px), thumb slate translucide, padding via border transparente.

---

## 13. Responsive

### Breakpoints (Tailwind defaults)

| Préfixe | Min-width |
|---|---|
| `sm:` | 640px |
| `md:` | 768px |
| `lg:` | 1024px |
| `xl:` | 1280px |
| `2xl:` | 1536px |

### Layout principal

- **Mobile (< md)** : topbar fixe en haut (h-14), sidebar en drawer (off-canvas
  par défaut, hamburger ouvre)
- **Desktop (≥ md)** : sidebar fixe à gauche (w-60), main content `ml-60`
- **TOC right rail** : visible uniquement `xl:` (≥ 1280px) sur package detail

### Skip-to-content link

Présent en `sr-only` en haut de chaque page, visible au focus clavier (Tab depuis
l'URL). Z-index 100 pour passer au-dessus de tout.

---

## 14. PWA / mobile

- `apple-touch-icon` (logo.png 512x512)
- `theme-color` light + dark via media query (`#f1f5f9` / `#020617`)
- `manifest.webmanifest` (install "Ajouter à l'écran d'accueil")
- `apple-mobile-web-app-capable` + `apple-mobile-web-app-status-bar-style`

---

## 15. Anti-patterns (à ne PAS faire)

- ❌ Couleurs hex hors palette → utiliser les tokens Tailwind / vars CSS
- ❌ `transition-colors` + `.interactive` en même temps → choisir l'un (interactive l'inclut déjà)
- ❌ `title="…"` HTML natif → toujours `data-tu-tooltip="…"`
- ❌ `window.confirm()` / `window.alert()` → `tu.confirm()` / `tu.alert()`
- ❌ Emoji dans l'UI (sauf drapeaux Twemoji)
- ❌ `padding: 7px` ou autres valeurs hors échelle → respecter le 4px-grid
- ❌ Box-shadow comme focus ring → utiliser `:focus-visible` global
- ❌ Z-index > 80 → casse l'ordre des tooltips
- ❌ Toast sans `tone` → toujours préciser info/success/warning/danger

---

## 16. Conventions de classes Tailwind

Ordre canonique dans les attributs `class=` :

1. **Layout** : `flex`, `grid`, `block`, `inline-*`
2. **Positionnement** : `absolute`, `fixed`, `top-0`, `right-0`, `z-*`
3. **Box model** : `w-*`, `h-*`, `p-*`, `m-*`, `gap-*`
4. **Typographie** : `text-*`, `font-*`, `tracking-*`, `leading-*`
5. **Background** : `bg-*`
6. **Bordure** : `border`, `border-*`, `rounded-*`
7. **États** : `hover:*`, `focus:*`, `active:*`, `disabled:*`, `dark:*`
8. **Animation** : `transition-*`, `duration-*`, `ease-*`

Pas une règle dure mais aide à scanner les éléments visuellement.

---

## 17. Références

- `src/flox_uploader/web/templates/base.html` — design tokens (Tailwind config + CSS vars)
- `src/flox_uploader/web/templates/_components.html` — macros (button, badge, card, empty_state, input_text, page_header, link_button)
- `src/flox_uploader/web/templates/_icons.html` — bibliothèque Lucide inline
- `pyproject.toml` — `version = "0.3.0"`
