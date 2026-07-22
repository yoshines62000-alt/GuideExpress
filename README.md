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

Au-delà de SmartScreen, un antivirus tiers (notamment en environnement
d'entreprise, souvent plus agressif que Windows Defender grand public) peut
occasionnellement mettre l'exécutable en quarantaine ou le bloquer au
démarrage : voir [Limites connues](#limites-connues) pour le détail et la
marche à suivre.

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
- Les captures d'écran brutes restent sur le disque
  (`~/.guide_express/sessions/`) ; rien n'est exporté sans relecture explicite.
- La rédaction de zones sensibles utilise un rectangle opaque, pas un flou —
  mais elle ne s'applique qu'à l'export : la capture brute (non rédigée) reste
  dans `~/.guide_express/sessions/`. **GuideExpress ne supprime jamais
  automatiquement ces sessions** : si vous partagez votre ordinateur, pensez
  à les supprimer après avoir exporté un guide contenant des informations
  sensibles — via l'écran "Gérer les sessions enregistrées" (sélection
  multiple avec Ctrl/Shift-clic, ou suppression en un coup de toutes les
  sessions plus anciennes qu'un nombre de jours donné), ou en vidant le
  dossier manuellement.

## Limites connues

### Clics dans une fenêtre lancée en tant qu'administrateur

GuideExpress capture les clics via un « hook » souris global bas niveau
(nécessaire pour enregistrer même quand la fenêtre de GuideExpress n'a pas le
focus, puisque vous travaillez dans d'autres applications pendant
l'enregistrement) — voir la section [Installation](#installation), à propos
de `pynput`. GuideExpress lui-même **ne demande jamais d'élévation** : il
tourne toujours au niveau de droits de votre session Windows normale.

Windows applique une barrière de sécurité (UIPI, *User Interface Privilege
Isolation*) qui empêche un processus non élevé de recevoir les clics destinés
à une fenêtre elle-même lancée **en tant qu'administrateur** (un assistant
d'installation, un panneau de configuration protégé, un outil admin...). Si
une étape de votre procédure se déroule dans une telle fenêtre, le clic n'y
sera **pas capturé** — c'est une limite de sécurité du système d'exploitation,
pas un bug de GuideExpress.

Pendant un enregistrement actif, GuideExpress surveille la fenêtre au premier
plan et affiche un avertissement explicite dans la fenêtre flottante
(« Attention : fenêtre administrateur au premier plan ») dès qu'elle est
détectée comme élevée, pour que vous ne découvriez pas l'étape manquante
seulement en relisant votre guide. Si vous savez à l'avance qu'une procédure
passera par une fenêtre élevée, la seule solution est de lancer GuideExpress
lui-même « en tant qu'administrateur » (clic droit sur l'exécutable →
Exécuter en tant qu'administrateur) le temps de cet enregistrement — une
instance élevée peut capturer les clics des fenêtres non élevées aussi, donc
à réserver aux cas où c'est réellement nécessaire.

### Risque de faux positif antivirus

Un hook souris global combiné à une capture d'écran automatique est un
schéma comportemental proche de ce que les moteurs antivirus heuristiques
associent aux outils de type keylogger/spyware — même si GuideExpress
n'intercepte **aucune frappe clavier** (voir [Confidentialité](#confidentialité))
et ne transmet jamais rien hors de votre machine. Combiné au fait que
l'exécutable n'est pas signé numériquement (voir ci-dessus), certains
antivirus — plus particulièrement en environnement d'entreprise — peuvent
mettre l'exécutable en quarantaine ou le bloquer silencieusement, sans lien
avec un quelconque bug du code.

Pour limiter ce risque, l'exécutable publié n'utilise **pas** de compression
UPX (`upx=False` dans `GuideExpress.spec`) : UPX est une technique également
très utilisée par des malwares pour échapper à la détection par signature,
et sa présence est un facteur aggravant bien identifié pour les faux positifs
sur les exécutables PyInstaller. Si votre antivirus signale néanmoins
l'exécutable, vous pouvez vérifier sa réputation par vous-même avant de
l'exécuter, par exemple en le soumettant à
[VirusTotal](https://www.virustotal.com/) (analyse par plusieurs dizaines de
moteurs antivirus) plutôt que de vous fier à un seul verdict.

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

Les tests de l'export PDF nécessitent une dépendance supplémentaire
([`pypdf`](https://pypdf.readthedocs.io/), pour relire et vérifier le PDF
généré), non requise pour l'application elle-même : installez
`requirements-dev.txt` avant de lancer la suite.

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover tests -v
```

## Structure du projet

```
capture.py          # modele Step, rendu des annotations/redactions, logique pure
recorder.py          # ecoute des clics (pynput) et capture d'ecran, isole du reste
export.py            # export HTML autonome / Markdown
gui.py                # interface graphique Tkinter
tests/                # tests automatises
requirements.txt      # dependances de l'application (Pillow, pynput)
requirements-dev.txt   # dependances additionnelles pour lancer les tests (pypdf)
Lancer.vbs            # raccourci de lancement double-clic (sans console)
Lancer.bat            # raccourci de lancement double-clic (avec console, pour debug)
GuideExpress.spec     # configuration de build PyInstaller (.exe autonome)
GuideExpress.manifest  # manifeste Windows embarque (DPI-aware, pas d'elevation)
icon.ico              # icone de l'application et de l'executable
.gitignore
LICENSE               # licence MIT
README.md
```

## Licence

Ce projet est publié sous licence [MIT](LICENSE) : gratuit, open source, et
libre de réutilisation, modification et redistribution.

## Soutenir le projet

<div align="center">

**Cet outil est gratuit, open source, et le restera toujours.**
Pas de version payante, pas de fonctionnalité cachée derrière un paywall.

Si GuideExpress vous fait gagner du temps sur votre documentation, un petit
café est toujours très apprécié. 🙌

[![Offrez-moi un café sur Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/yoshines62000)

</div>
