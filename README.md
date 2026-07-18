# GuideExpress

Générateur de guides pas-à-pas illustrés, à partir de vos clics réels — gratuit,
open source, et 100 % local. Alternative libre à des outils comme
[Scribe](https://scribe.com/) ou [Tango](https://www.tango.us/), qui facturent
16 à 29 $ par utilisateur et par mois pour la même fonctionnalité de base.

Cliquez sur "Démarrer l'enregistrement", effectuez normalement la tâche à
documenter (dans n'importe quelle application), cliquez sur "Arrêter" : chaque
clic devient une étape illustrée, avec une capture d'écran annotée. Relisez,
réordonnez, masquez les zones sensibles, puis exportez en HTML autonome ou en
Markdown.

## Fonctionnalités

- **100 % local, zéro cloud** : aucune capture d'écran, aucune donnée n'est
  jamais envoyée où que ce soit. Tout reste sur votre machine.
- **Aucune capture de frappe clavier — jamais.** Seule la position des clics
  de souris est enregistrée. Un outil qui se prétend respectueux de la vie
  privée ne doit jamais s'approcher d'un enregistreur de frappe.
- **Rédaction de zones sensibles** : avant d'exporter, masquez n'importe quelle
  zone d'une capture (mot de passe visible, email, numéro de compte...) avec
  un rectangle plein — pas un flou, qui peut parfois laisser deviner ce qui
  est censé être caché.
- **Relecture avant export** : rien n'est jamais exporté sans que vous ayez pu
  voir, réordonner, modifier le texte ou supprimer chaque étape.
- **Export HTML autonome** : un seul fichier, images incluses (encodées en
  base64) — rien à oublier en le partageant.
- **Export Markdown** : fichier `.md` + dossier d'images, pour l'intégrer dans
  un wiki, un dépôt Git, une base de connaissances.
- **Gratuit et open source, pour toujours** : pas de version payante, pas de
  fonctionnalité verrouillée derrière un abonnement.

## Démarrage rapide

Double-cliquez sur **[`Lancer.vbs`](Lancer.vbs)** : la fenêtre de l'application
s'ouvre directement, sans console. Si c'est la première fois, installez
d'abord les dépendances (voir [Installation](#installation)).

Vous pouvez créer un raccourci sur le Bureau (clic droit sur `Lancer.vbs` →
Envoyer vers → Bureau) pour un accès en un clic.

## Installation

Nécessite Python 3.9+ avec Tkinter (inclus dans les installations standard de
Python sous Windows), plus deux dépendances légères :

```bash
python -m pip install -r requirements.txt
```

- **[Pillow](https://python-pillow.org/)** : capture d'écran et dessin des
  annotations sur les images.
- **[pynput](https://pynput.readthedocs.io/)** : écoute des clics de souris au
  niveau du système (nécessaire pour capturer un clic même quand la fenêtre de
  GuideExpress n'a pas le focus, puisque vous travaillez dans d'autres
  applications pendant l'enregistrement).

## Utilisation

1. Lancez l'application, donnez un titre à votre guide.
2. Cliquez sur **Démarrer l'enregistrement**. Une petite fenêtre flottante
   indique que l'enregistrement est actif et le nombre d'étapes capturées.
3. Effectuez normalement la tâche à documenter, dans n'importe quelle
   application. Chaque clic gauche crée une nouvelle étape.
4. Cliquez sur **Arrêter l'enregistrement**.
5. Dans l'écran de relecture :
   - modifiez le texte de chaque étape (une description par défaut est
     proposée à partir du nom de la fenêtre active) ;
   - réordonnez avec **Haut**/**Bas**, supprimez une étape avec **Supprimer** ;
   - cliquez sur **Rediger** pour masquer une zone sensible d'une capture
     (cliquez-glissez pour dessiner un rectangle plein).
6. Exportez en **HTML** (un seul fichier à partager) ou en **Markdown**
   (fichier + dossier d'images).

## Confidentialité

- Aucune donnée ne quitte votre machine : pas de compte, pas de serveur, pas
  de télémétrie.
- Aucune frappe clavier n'est jamais interceptée, seulement la position des
  clics de souris au moment où ils se produisent.
- Les captures d'écran brutes restent sur le disque le temps de la session
  (`~/.guide_express/sessions/`) ; rien n'est exporté sans relecture explicite.
- La rédaction de zones sensibles utilise un rectangle opaque, pas un flou.

## Tests

Une suite de tests automatisés couvre la logique pure (rendu des annotations,
non-destruction de l'image source, rédaction, réordonnancement, échappement
HTML/Markdown à l'export) et un scénario de bout en bout avec un vrai clic
système.

```bash
python -m unittest discover tests -v
```

## Structure du projet

```
capture.py          # modele Step, rendu des annotations/redactions, logique pure
recorder.py          # ecoute des clics (pynput) et capture d'ecran, isole du reste
export.py            # export HTML autonome / Markdown
gui.py                # interface graphique Tkinter
tests/                # tests automatises
requirements.txt      # dependances (Pillow, pynput)
Lancer.vbs            # raccourci de lancement double-clic (sans console)
Lancer.bat            # raccourci de lancement double-clic (avec console, pour debug)
README.md
```

## Soutenir le projet

<div align="center">

**Cet outil est gratuit, open source, et le restera toujours.**
Pas de version payante, pas de fonctionnalité cachée derrière un paywall.

Si GuideExpress vous fait gagner du temps sur votre documentation, un petit
café est toujours très apprécié. 🙌

[![Offrez-moi un café sur Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/yoshines62000)

</div>
