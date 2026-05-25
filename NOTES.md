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
- il manque les extraction d'image des format Epub ! il nous les faut !
- sur la page detail du package : "HS.LARGO.WINCH.INTEGRALE.FRENCH.BD.PDF.Ebook-notag.CBZ-NoTAG" dans la section "Contenu du torrent" je n'arrive pas a deplier les dossier qui se trouve dans le dossier. il y a des bug d'affichage le bouton sembler reagire mais rien ne se deplis. j'ai reussi a un moment mais impossible de le refermer.

# Release  : tout probleme lié au nom ou a la correspondance d'un release - si corredpondance pas trouvé tu dois mettre en place un moyen de le trouver.
- le fichier : "Andrzej.Sapkowski.The.Witcher.T03.Le.Sang.des.Elfes.2026.FRENCH.MP3.VBR-COZY" a donner "Andrzej.Sapkowski.The.Witcher.T3.Le.Sang.Des.Elfes.2026.FRENCH.VBR-COZY.2026.MP3-NoTAG" mais je pense que "Cozy" est la team. et la correspondance etait facil a trouver on aurait du tomber sur ca : https://www.google.ca/books/edition/Sorceleur_Witcher_T3_Le_Sang_des_elfes_t/4eeGAQAAQBAJ?hl=fr&gbpv=0. peux tu implementer la logique pour ne pas le rater ?
- le fichier "Andrzej.Sapkowski.The.Witcher.T08.La.Croisee.des.Corbeaux.2025.FRENCH.MP3.VBR-COZY" a donner "Andrzej.Sapkowski.The.Witcher.T8.La.Croisee.Des.Corbeaux.2025.FRENCH.VBR-COZY.2025.MP3-NoTAG" mais pareil "cozy est la team" et la correspondance est : "https://www.google.ca/books/edition/Sorceleur_Witcher_La_Crois%C3%A9e_des_corbea/TuRpEQAAQBAJ?hl=fr&gbpv=0"
- le release : "Decoupe en tranches (10354)" "Zep.Decoupe.En.Tranches.10354.PDF-NoTAG" aurait du trouver facilement ceci : "https://www.google.ca/books/edition/D%C3%A9coup%C3%A9_en_tranches/OxVCBAAAQBAJ?hl=fr&gbpv=0" 
- le dossier : LARGO.WINCH.INTEGRALE.FRENCH.BD.PDF.CBZ.Ebook-NoTag donne "HS.LARGO.WINCH.INTEGRALE.FRENCH.BD.PDF.Ebook-notag.CBZ-NoTAG" mais ne trouve pas de correspondance, pourtant je le trouve sans probleme sur "https://www.google.ca/books/edition/Largo_Winch_int%C3%A9grale/cvrKBAAAQBAJ?hl=fr&gbpv=0". deplus on a a l'interieur deux formats pdf et cbz dans 2 dossier distinct il faudrait garder cette hierarchi quand on prensente le contenu du torrent dans la presentation bbcode.
- "Le.Massacre.De.Crac.H.Pierre.Bertin.2025.FRENCH.[EPUB]-NOTAG" donne "Pierre.Bertin.Le.Massacre.De.Crac.H.Pierre.Bertin.2025.FRENCH.-NOTAG.2025.FRENCH.EPUB-NoTAG" "2025 french notag" ne fait evidement pas partis du nom ! on a bien un isbn 
9782355507786 : la correspondance etait simple a trouver pourtant ! : "https://www.google.ca/books/edition/Le_massacre_de_Crac_h/eJGgEQAAQBAJ?hl=fr&gbpv=0". autre probleme avec ce release le resumé contien des caractere etrange "< div>
< p>Quand le c..." et a la fin "... sans l’autre.</ p >< /div>" qui vont se retrouver egalement dans la presentaiton bbcode. il faut que le texte soit un format clean.
- le fichier "Lucy.Score.Knockemout.1.Ces.Choses.Qu.On.N.Oublie.Pas.2023.FRENCH.MP3.128kbps-NOTAG" correspondance : "https://www.google.ca/books/edition/Ces_choses_qu_on_n_oublie_pas_Tome_1/kzG0EAAAQBAJ?hl=fr"
- le release "Spartacus.Blood.And.Sand.01.2011.ENGLISH.PDF-NoTAG" n'a pas la bonne correspondance, on tombe sur "https://catalogue.bnf.fr/ark:/12148/cb451300150" mais ca ne correspond pas  ca auraitr du etre "https://www.chasse-aux-livres.fr/prix/B003BQWORW/spartacus-blood-and-sand-1-32-pages-full-color-spartacus-blood-and-sand-volume-1?query=Spartacus%20-%20Blood%20and%20Sand%2001" mais je ne trouve rien de mieux.
- le fichier : "Lemire.Sorrentino.Le.mythe.de.l.Ossuaire.Tome.1.Le.passage.2023.FRENCH.PDF-NoTag.pdf" aurait du trouver cette correspondance : https://www.google.ca/books/edition/Le_Mythe_de_l_Ossuaire_Le_Passage/Qiy9EAAAQBAJ?hl=fr&gbpv=0 et ainsi avoir toute les informationé
- le fichier "Là où gisait le corps (One Shot) (Delcourt) [Digital-2984] (TCH).cbz" aurait du trouver cette correspondance : "https://www.google.ca/books/edition/L%C3%A0_o%C3%B9_gisait_le_corps/b1u20AEACAAJ?hl=fr" 
- le fichier "Koma.Warita.Riku.Tsuchida.Miraculous.Ladybug.Et.Chat.Noir.T2.2023.FR.PDF-NoTag.pdf" aurait du facilemet nous trouver cette correspondance : https://www.google.ca/books/edition/Miraculous_T02/9LXaEAAAQBAJ?hl=fr&gbpv=0 ISBN : 9782384961726, 2384961721
- "Dominique.Auzias.Jean-Paul.Labourdette.et.autres.POITIERS.2026.Avec.Photos.2025.FRENCH.EPUB-NoTAG" les infos etait claire et on aurait du trouver : https://www.google.ca/books/edition/Guide_Poitiers_2026_Petit_Fut%C3%A9_Escapade/Nw2eEQAAQBAJ?hl=fr 
- - "\\FOOLNAS\arr-data\torrents\completed\Elle.s.appelait.Tomoji.FR.NoTag.cbz" on devrait avoir trouver les info ici : https://www.google.ca/books/edition/_/AQVqBgAAQBAJ?hl=fr&sa=X&ved=2ahUKEwinyMzyn9OUAxWjDHkGHR_BK2gQ7_IDegQIEBAC 


# logique system : tout probleme lié a la logique script.
- le release : "Decoupe en tranches (10354)" dans ce release on a un fichier "cover" on peut l'utiliser en backup et l'heberger sur IMGBB.
- le fichier : "La.Trilogie.Des.Vents.T03.Les.Vents.Furieux.Mercedes.Lackey.2011.FRENCH.[EPUB]-NOTAG" nous trouve le ISBN : 9782811204808 on aurait pu trouver aussi le lien googlebook : "https://www.google.ca/books/edition/La_Trilogie_des_Vents_T3_Les_Vents_furie/oa-GAQAAQBAJ?hl=fr&gbpv=0" etrangement le isbn ne correspond pas. mais avec le premier isbn trouvé on pourrait se rapatrier sur des lien comme "https://www.chasse-aux-livres.fr/prix/2811204806/la-trilogie-des-vents-tome-3-les-vents-furieux" ou "https://www.leslibraires.ca/livres/trilogie-des-vents-la-t-3-mercedes-lackey-9782811204808.html?srsltid=AfmBOorgDe4yMK7CEfEzUNVx9y07aoRR38EVRGOa-e00oV5x_d6etyFM" et recuperer les infos utiles. plus on a d'option plus on recupere d'info. on continu tant qu'on a pas toute les infos. j'ai mis 2 site de livrary mais je te laisse trouver quel sont les meilleure site qu'on peut rajouter.

#  UX/UI : truc moche, pas évident, manque, friction
-  peux on les mettre la taille des screenshots sur la rpesentation bbcode en [img=250].


# Feature : envie de quelque chose qui n'existe pas


# Question : pas sûr du comportement attendu


# Bonus : charte API  IMGBB 

Version 1 de l’API
L'API v1 de Imgbb vous permet de téléverser des images.

f411e93b2b56db305e76f3d3a4704f37


Méthode de requête
Les appels à l'API v1 peuvent être effectués avec les méthodes de requête POST ou GET, mais comme les requêtes GET sont limitées par la longueur maximale d'URL autorisée, vous devriez privilégier la méthode POST.

Téléversement d’image
https://api.imgbb.com/1/upload

Paramètres
key (obligatoire)
La clé API.
image (obligatoire)
Un fichier binaire, des données base64 ou une URL d'image (jusqu'à 32 MB).
name (optionnel)
Le nom du fichier ; il est détecté automatiquement si vous téléversez un fichier en utilisant POST et multipart/form-data.
expiration (optionnel)
Activez ceci si vous souhaitez que les téléversements soient automatiquement supprimés après un certain délai (en secondes, 60-15552000).
Exemple d’appel
curl --location --request POST "https://api.imgbb.com/1/upload?expiration=600&key=YOUR_CLIENT_API_KEY" --form "image=R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"

Remarque : utilisez toujours POST lors du téléversement de fichiers locaux. L'encodage d'URL peut altérer la source base64 en raison des caractères encodés ou simplement à cause de la limite de longueur d'URL lors de l'utilisation de GET.

Réponse de l’API
Les réponses de l'API v1 affichent toutes les informations des images téléversées au format JSON.

Dans la réponse JSON, les en-têtes incluront des codes d'état pour vous permettre de déterminer facilement si la requête était OK. Elle inclura également la propriété status.

Exemple de réponse (JSON)
{
	"data": {
		"id": "2ndCYJK",
		"title": "c1f64245afb2",
		"url_viewer": "https://ibb.co/2ndCYJK",
		"url": "https://i.ibb.co/w04Prt6/c1f64245afb2.gif",
		"display_url": "https://i.ibb.co/98W13PY/c1f64245afb2.gif",
		"width":"1",
		"height":"1",
		"size": "42",
		"time": "1552042565",
		"expiration":"0",
		"image": {
			"filename": "c1f64245afb2.gif",
			"name": "c1f64245afb2",
			"mime": "image/gif",
			"extension": "gif",
			"url": "https://i.ibb.co/w04Prt6/c1f64245afb2.gif",
		},
		"thumb": {
			"filename": "c1f64245afb2.gif",
			"name": "c1f64245afb2",
			"mime": "image/gif",
			"extension": "gif",
			"url": "https://i.ibb.co/2ndCYJK/c1f64245afb2.gif",
		},
		"medium": {
			"filename": "c1f64245afb2.gif",
			"name": "c1f64245afb2",
			"mime": "image/gif",
			"extension": "gif",
			"url": "https://i.ibb.co/98W13PY/c1f64245afb2.gif",
		},
		"delete_url": "https://ibb.co/2ndCYJK/670a7e48ddcb85ac340c717a41047e5c"
	},
	"success": true,
	"status": 200
}
