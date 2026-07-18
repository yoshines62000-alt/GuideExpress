# GuideExpress

[![Dernière version](https://img.shields.io/github/v/release/yoshines62000-alt/GuideExpress?label=derni%C3%A8re%20version)](https://github.com/yoshines62000-alt/GuideExpress/releases/latest)
[![Téléchargements](https://img.shields.io/github/downloads/yoshines62000-alt/GuideExpress/total?label=t%C3%A9l%C3%A9chargements)](https://github.com/yoshines62000-alt/GuideExpress/releases/latest)

**[⬇️ Télécharger l'exécutable (.exe) — aucune installation requise](https://github.com/yoshines62000-alt/GuideExpress/releases/latest)**

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

1. [**Téléchargez `GuideExpress.exe`**](https://github.com/yoshines62000-alt/GuideExpress/releases/latest)
   depuis la dernière release.
2. Double-cliquez dessus : la fenêtre de l'application s'ouvre directement,
   sans installation, sans Python.

L'exécutable n'étant pas signé numériquement, Windows SmartScreen peut
afficher un avertissement au premier lancement : cliquez sur **Informations
complémentaires** puis **Exécuter quand même**.

## Lancer depuis le code source

Alternative à l'exécutable, pour les développeurs ou par souci de
transparence (voir [Installation](#installation) pour les dépendances) :
double-cliquez sur **[`Lancer.vbs`](Lancer.vbs)** — la fenêtre s'ouvre
directement, sans console. Vous pouvez créer un raccourci sur le Bureau (clic
droit sur `Lancer.vbs` → Envoyer vers → Bureau) pour un accès en un clic.

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

## Créer un exécutable autonome (.exe)

Pour distribuer l'outil sans que le destinataire ait besoin d'installer
Python ni les dépendances, un exécutable Windows autonome peut être généré
avec [PyInstaller](https://pyinstaller.org/) :

```bash
python -m pip install pyinstaller
python -m PyInstaller GuideExpress.spec
```

L'exécutable est produit dans `dist/GuideExpress.exe` (fichier unique, sans
console). Le fichier `.spec` du dépôt fixe la configuration de build pour un
résultat reproductible. Les dossiers `build/` et `dist/` ne sont pas suivis
par Git.

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
GuideExpress.spec     # configuration de build PyInstaller (.exe autonome)
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
