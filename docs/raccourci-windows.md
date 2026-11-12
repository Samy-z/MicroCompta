# Les raccourcis Windows

Un raccourci est un petit fichier `.lnk` qui lance l'application d'un double clic, avec son
icône et sans fenêtre noire. Ce guide explique d'où viennent ceux de MicroCompta et comment les
recréer, les ajouter au démarrage de Windows ou les supprimer. Il suppose que
l'[installation](installation.md) est faite.

## Ceux que l'installation crée

Au premier lancement de `run.bat`, trois raccourcis identiques sont créés :

| Où | À quoi il sert |
| --- | --- |
| Le dossier de l'application (`MicroCompta.lnk`) | Il sert de témoin à `run.bat` : tant qu'il existe, `run.bat` ne recrée pas les raccourcis. |
| Le Bureau | Lancer l'application. |
| Le menu Démarrer | Retrouver l'application en tapant « MicroCompta » après un appui sur la touche Windows. |

Chaque raccourci lance `pythonw.exe` depuis le sous-dossier `.venv` de l'application, avec les
arguments `-m microcompta`. `pythonw.exe` est la version de Python qui n'ouvre pas de fenêtre de
console. Le raccourci démarre dans le dossier de l'application et prend l'icône
`assets\MicroCompta.ico`.

## Recréer les raccourcis

Il faut les recréer après avoir déplacé le dossier de l'application, car ils contiennent son
chemin complet.

1. Ouvrez le dossier de l'application dans l'Explorateur de fichiers.
2. Cliquez dans la barre d'adresse, tapez `cmd` et appuyez sur Entrée. Une invite de commandes
   s'ouvre dans ce dossier.
3. Tapez la commande suivante et appuyez sur Entrée :

```bash
.venv\Scripts\python.exe scripts\make_shortcut.py
```

La commande affiche le chemin de chaque raccourci créé. Elle remplace les anciens raccourcis du
même nom au même endroit.

Supprimer `MicroCompta.lnk` dans le dossier de l'application puis relancer `run.bat` donne le
même résultat, sans taper de commande.

## Lancer MicroCompta avec Windows

Les rappels d'échéance ne partent que si l'application tourne. Pour qu'elle démarre avec Windows
et attende dans la zone de notification, ajoutez un raccourci au dossier de démarrage, une seule
fois :

```bash
.venv\Scripts\python.exe scripts\make_shortcut.py --startup
```

Ce raccourci est placé dans votre dossier de démarrage personnel,
`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`. Il ne concerne que votre compte
Windows.

## Ne créer que le raccourci du dossier

```bash
.venv\Scripts\python.exe scripts\make_shortcut.py --project-only
```

Cette variante ne touche ni au Bureau ni au menu Démarrer.

## Supprimer les raccourcis

- **Bureau et dossier de l'application** : supprimez le fichier `MicroCompta.lnk`.
- **Menu Démarrer** : tapez `%APPDATA%\Microsoft\Windows\Start Menu\Programs` dans la barre
  d'adresse de l'Explorateur, puis supprimez `MicroCompta.lnk`.
- **Démarrage automatique** : appuyez sur Windows + R, tapez `shell:startup` et appuyez sur
  Entrée, puis supprimez `MicroCompta.lnk`.

Supprimer un raccourci ne touche ni l'application ni vos registres.

## Comment le script fonctionne

`scripts\make_shortcut.py` demande à PowerShell, l'outil de commandes intégré à Windows, de
fabriquer le raccourci. L'application n'a donc besoin d'aucune bibliothèque de plus pour cela. Le
script ne marche que sous Windows ; ailleurs, il le dit et s'arrête.

## Si le raccourci n'apparaît pas sur le Bureau

Le script écrit dans le dossier `Desktop` de votre profil Windows. Si votre Bureau est synchronisé
par OneDrive, Windows peut afficher un autre dossier, et le raccourci n'y apparaîtra pas. Ce cas
n'a pas été essayé. Le raccourci du menu Démarrer reste disponible dans tous les cas.
