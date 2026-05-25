# Notes de développement

## 📌 Instructions pour Claude Code

Ce fichier contient des notes rapides sur le projet. Elles sont écrites à la volée, 
sans grand soin pour les détails ou la précision technique. **Ne les prends pas 
au pied de la lettre.**

### Comment interpréter ces notes

1. **Cerne l'intention, pas la formulation.** Chaque note exprime un besoin, un 
   problème à résoudre ou une direction. Identifie le *vrai* besoin derrière les 
   mots, même si la formulation est floue, incomplète ou maladroite.

2. **Remets en question les solutions proposées.** Si une note suggère une 
   approche technique, traite-la comme une *piste*, pas comme une instruction. 
   Si tu connais une meilleure façon de faire (plus simple, plus robuste, plus 
   maintenable, plus performante, plus idiomatique), propose-la et explique 
   brièvement pourquoi.

3. **Détecte ce qui manque.** Les notes sont souvent incomplètes : cas limites 
   non considérés, validations oubliées, gestion d'erreurs absente, impact sur 
   d'autres parties du code non évalué. Identifie ces angles morts et soulève-les.

4. **Propose plus que ce qui est demandé — quand c'est pertinent.** Si en lisant 
   une note tu vois une amélioration logique, une fonctionnalité complémentaire 
   évidente, ou une refonte qui résoudrait plusieurs notes d'un coup, mentionne-le. 
   Sans pour autant dériver : reste centré sur le besoin exprimé.

5. **Pose des questions si l'intention est ambiguë.** Mieux vaut clarifier avant 
   de coder que de partir dans la mauvaise direction. Si plusieurs interprétations 
   raisonnables existent, demande laquelle correspond à mon intention.

### Ton processus suggéré pour chaque note

1. **Reformule** ce que tu comprends de la note (en une phrase) pour valider la 
   compréhension.
2. **Évalue** la solution proposée si j'en ai donné une : est-elle bonne ? 
   sous-optimale ? carrément à éviter ?
3. **Propose** ton approche, avec une brève justification si elle diffère de la mienne.
4. **Signale** les implications, dépendances ou impacts ailleurs dans le code.
5. **Implémente** une fois qu'on est aligné — ou pose tes questions avant.

### Ce que je veux éviter

- Que tu codes littéralement une solution boiteuse juste parce que je l'ai écrite.
- Que tu restes silencieux sur un meilleur chemin parce que je ne l'ai pas demandé.
- Que tu te lances tête baissée sur une note ambiguë sans clarifier.

Bref : sois un collaborateur qui pense, pas un exécutant qui transcrit.

---

## Notes

# Bug : ça plante / résultat faux / régression
- les lien ISBN sur la page detail section Livre. mene sur ce genre de lien : "https://www.bnf.fr/fr/recherche/general?query=9782305108117" ca ne fait pas de sens, soit il existe vraiment un lien pour les ISBN soit on ne met pas d'hyper lien.


# Release  : tout probleme lié au nom ou a la correspondance d'un release
- "\\FOOLNAS\arr-data\torrents\completed\Elle.s.appelait.Tomoji.FR.NoTag.cbz" sur la page de presentation on a le cover dans la page Livre (super) mais on a aucune autre info, comment est-ce possible ? le lien google-book tous ramene ici : https://www.google.com/search?tbm=bks&q=Elle.s.appelait.Tomoji.FR.NoTag%20 mais on devrait pas plutôt etre ici : https://www.google.ca/books/edition/_/AQVqBgAAQBAJ?hl=fr&sa=X&ved=2ahUKEwinyMzyn9OUAxWjDHkGHR_BK2gQ7_IDegQIEBAC et ainsi avoir toute les informations ? (resume auteur etc...).
- "Dominique.Auzias.Jean-Paul.Labourdette.et.autres.POITIERS.2026.Avec.Photos.2025.FRENCH.EPUB-NoTAG" les infos etait claire et on aurait du trouver : https://www.google.ca/books/edition/Guide_Poitiers_2026_Petit_Fut%C3%A9_Escapade/Nw2eEQAAQBAJ?hl=fr a la place on a un lien googleBooks mais incomplet "https://www.google.com/search?tbm=bks&q=POITIERS%202026%20%28avec%20photos%29%20Dominique%20Auzias%2C%20Jean-Paul%20Labourdette%20et%20autres" on aurait ainsi le vrai nom : "Guide Poitiers 2026 Petit Futé: Escapades dans la Vienne".
- le package "Dominique.Auzias.Jean-Paul.Labourdette.POITOU.2024.Petit.Fute.2024.FRENCH.EPUB-NoTAG" a unle ISBN suivant 9782305108117 mais sur google book ici : https://www.google.ca/books/edition/POITOU_2024_Petit_Fut%C3%A9/U9cBEQAAQBAJ?hl=fr j'ai les isbn suivant : ISBN : 9782305108124, 2305108125 pourquoi ?
- le fichier "Koma.Warita.Riku.Tsuchida.Miraculous.Ladybug.Et.Chat.Noir.T2.2023.FR.PDF-NoTag.pdf" aurait du facilemet nous trouver cette correspondance : https://www.google.ca/books/edition/Miraculous_T02/9LXaEAAAQBAJ?hl=fr&gbpv=0 ISBN : 9782384961726, 2384961721
- le fichier : "Lemire.Sorrentino.Le.mythe.de.l.Ossuaire.Tome.1.Le.passage.2023.FRENCH.PDF-NoTag.pdf" aurait du trouver cette correspondance : https://www.google.ca/books/edition/Le_Mythe_de_l_Ossuaire_Le_Passage/Qiy9EAAAQBAJ?hl=fr&gbpv=0 et ainsi avoir toute les informationé
- le fichier "Là où gisait le corps (One Shot) (Delcourt) [Digital-2984] (TCH).cbz" aurait du trouver cette correspondance : "https://www.google.ca/books/edition/L%C3%A0_o%C3%B9_gisait_le_corps/b1u20AEACAAJ?hl=fr" 

# logique system : tout probleme lié a la logique script.
- "Dominique.Auzias.Jean-Paul.Labourdette.et.autres.POITIERS.2026.Avec.Photos.2025.FRENCH.EPUB-NoTAG" sur ce release j'ai le warning :"Format fichier manquant — format Gemini incomplet" mais le format meme si il n,est pas dans le nom se trouve dans le fichier (le format du fichier) a savoir epub, peut etre etre moins punitif sur le warning du style "format absent dans le nom du fichier, recuperer sur le fichier lui meme" et juste un -1
- le package "Dominique.Auzias.Jean-Paul.Labourdette.POITOU.2024.Petit.Fute.2024.FRENCH.EPUB-NoTAG" a trouver les bonne infos c'est super mais le lien googlebook nous amene ici "https://www.google.com/search?tbm=bks&q=POITOU%202024%20Petit%20Fut%C3%A9%20Dominique%20Auzias%2C%20Jean-Paul%20Labourdette" il devrait peut etre plus nous enmener ici : "https://www.google.ca/books/edition/POITOU_2024_Petit_Fut%C3%A9/U9cBEQAAQBAJ?hl=fr" 
- le package "Lemire.Sorrentino.Le.Mythe.De.L.Ossuaire.Tome.1.Le.Passage.2023.FRENCH.Pdf-notag.PDF-NoTAG" a le warning "Format fichier manquant — format Gemini incomplet" mais dans le nom du fichier on a "pdf" "Lemire.Sorrentino.Le.mythe.de.l.Ossuaire.Tome.1.Le.passage.2023.FRENCH.PDF-NoTag.pdf". on aurait donc pas du avoir se warning je pense.

#  UX/UI : truc moche, pas évident, manque, friction
- les deux banner "Format de release Gemini incomplet
Le format obligatoire Gemini est Auteur.Titre.Date.Langue.Format-TEAM. Il manque : Format.
Le release_name est généré à partir de ces champs. Tu peux les compléter manuellement dans la section Re-préparer le package ci-dessous, puis relancer.
Compléter manuellement" et "Présentation incomplète
Champs manquants pour la fiche tracker : ISBN. La fiche uploadée sera plus pauvre que si tu complètes manuellement.
Éditer la présentation" sont super ! mais elle devrait se trouver en dessous de la section "Detail du score"


# Feature : envie de quelque chose qui n'existe pas
- si on trouve les bon date de livre penses tu qu'on puise integrer le cover dans la presentation bbcode (comme l'affiche de film pour les film)

# Question : pas sûr du comportement attendu
- sur la page Upload de gemini quand on choisis livre on a deux ligne qu'on peut remplir pour uploader un cover et une banner (voir screenshot) soit en uploadant l'image soit le lien URL - dis moi si tu penses qu'on peut implementer ces fonctions exactemetn comme tel et si on a pour sur la correspondance API pour l'envoyer au bon endroit depuis notre app ? soit honnete et fait les recherche necessaire :"G3MINI TR4CK3R - TORRENT API.pdf"
- ou a tu recuperer le cover pour les release suivant : "Guide Poitiers 2026 Petit Futé- Escapades dans la Vienne.epub" et "Elle.s.appelait.Tomoji.FR.NoTag.cbz" peut-on les utiliser ailleur ? presentation BBcode ? COver de l'upload (voir note plus haut) ?
- penses tu qu'on est capable d,extraire des images, screenshot, des livre peut importe leur format de les heberger et de les integrer dans la presentation bbcode ? si oui comment ca serait possible ?