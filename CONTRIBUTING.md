# Contribuer à Flox Uploader

Merci de t'intéresser au projet. Quelques règles simples pour que ça se passe bien.

## Avant de coder

1. **Ouvre une issue** pour discuter le changement avant de commencer un gros
   travail. Évite que tu passes des heures sur un PR qui ne matche pas la
   direction du projet.
2. **Lis** `PLAN-V1.md` (roadmap stratégique) et `CHARTE.md` (design system).
   Si ton changement contredit une décision actée, on en parle d'abord.
3. **Lis** `NOTES.md` (instructions Claude / notes de dev) pour le contexte.

## Workflow

1. Fork le repo
2. Crée une branche : `feature/ma-feature` ou `fix/le-bug`
3. Fais tes changements en respectant la charte
4. Garde la suite de tests verte (`pytest tests/`)
5. Ajoute des tests si tu ajoutes du comportement
6. Mets à jour `CHANGELOG.md` dans la section `[Unreleased]`
7. Ouvre une Pull Request avec :
   - Description claire de ce que tu changes et pourquoi
   - Référence à l'issue liée (s'il y en a une)
   - Captures d'écran si c'est un changement UI

## Style de code

- **Python** : on suit PEP 8, lignes max 100 chars, type hints obligatoires sur les fonctions publiques
- **Templates Jinja** : indentation 4 espaces, classes Tailwind dans l'ordre canonique (cf. `CHARTE.md § 16`)
- **JavaScript** : pas de framework, vanilla JS uniquement. Préfère les fonctions pures aux classes
- **Commits** : un commit par "étape logique", message explicite en français ou anglais

## Tests

```bash
pip install -e .[dev]
pytest tests/ -v
```

622 tests doivent passer en `v0.3.0`. Toute régression bloque le merge.

## Design

Avant d'ajouter un composant ou de modifier un style, lis `CHARTE.md`. Si la
charte ne couvre pas ton cas, **ajoute la nouvelle convention au document
avant de coder**, pas après.

## Questions ?

- Issues GitHub pour bugs et features
- Pas de Discord / email — tout passe par les issues, c'est plus traçable

## Code of Conduct

Sois respectueux. Pas de discrimination, pas de harcèlement, pas de
personal attacks. Si tu n'es pas d'accord avec une décision, argumente sur
les faits. Les contributeurs qui dévient sont retirés du projet.
