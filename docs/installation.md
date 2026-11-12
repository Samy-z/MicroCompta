# Installer MicroCompta

Ce guide s'adresse à quelqu'un qui utilise Windows sans être développeur. Il suffit de savoir
télécharger un fichier et ouvrir un dossier. Les autres termes sont expliqués là où ils
apparaissent.

## Ce qu'il faut

- **Windows 10 ou 11.** L'application a été utilisée sur Windows 11. Le script prévu pour macOS et
  Linux n'a jamais été testé.
- **Python 3.11 ou plus récent.** Python est le langage dans lequel l'application est écrite. Elle
  a été utilisée avec Python 3.13. Le programme d'installation se télécharge sur
  [python.org](https://www.python.org/downloads/). Pendant l'installation, cochez la case
  « Add python.exe to PATH », qui permet à Windows de trouver Python.
- **Environ 770 Mo d'espace disque.** C'est la taille mesurée sur une installation Windows 11
  avec Python 3.13, dont 656 Mo pour PySide6, la bibliothèque qui dessine les fenêtres de l'application.

## Installer

1. Sur la page GitHub du projet, cliquez sur le bouton « Code »,
   puis sur « Download ZIP ». Si vous utilisez git, vous pouvez aussi cloner le projet.
2. Décompressez le fichier dans un dossier au chemin court, par exemple `C:\MicroCompta`. Un
   chemin trop long fait échouer l'installation de PySide6, qui contient des fichiers aux noms
   très longs. Le ZIP contient un dossier `MicroCompta-main` : c'est lui, le dossier de
   l'application.
3. Ouvrez ce dossier et double-cliquez sur `run.bat`.
4. Windows peut vous demander confirmation, car le fichier vient d'internet. S'il affiche
   « Windows a protégé votre ordinateur », cliquez sur « Informations complémentaires », puis sur
   « Exécuter quand même ». S'il demande « Voulez-vous exécuter ce fichier ? », cliquez sur
   « Exécuter ».

Une fenêtre noire s'ouvre et affiche la progression. Le script crée d'abord un environnement
virtuel dans le sous-dossier `.venv`, c'est-à-dire une copie de Python réservée à MicroCompta.
Il y télécharge et installe ensuite les bibliothèques nécessaires, ce qui peut prendre plusieurs
minutes selon votre connexion. Il crée les raccourcis, puis ouvre l'application.

Les lancements suivants passent directement à l'ouverture. Si l'installation a été interrompue,
elle reprend au prochain lancement au lieu d'ouvrir une application incomplète.

## Premier lancement

La fenêtre des Paramètres s'ouvre d'elle-même. Saisissez votre nom, votre adresse et votre date
de début d'activité. Choisissez votre type d'activité et le rythme de vos déclarations, mensuel ou
trimestriel. Cochez l'ACRE si elle vous a été accordée : c'est une réduction de cotisations pour
les créateurs d'entreprise. Ces choix décident des taux et des échéances. Cliquez enfin sur
« Enregistrer ».

Votre SIREN, le numéro à 9 chiffres de votre entreprise, peut attendre : il n'est exigé que pour
émettre une facture définitive.

Fermez ensuite les Paramètres et ajoutez votre client : sur la page Clients, ou avec le bouton
« + » à côté de la liste des clients dans le volet de saisie. Pour un client imposable en France,
cochez la case « Imposable en France », sans quoi son chiffre d'affaires ne compterait pas pour
la franchise en base de TVA. Tant qu'aucun client n'existe, l'application s'ouvre sur la page
Clients. Le [guide d'utilisation](guide.md) décrit la suite.

## Où sont vos données

| Quoi | Où |
| --- | --- |
| Vos registres (la base de données) | `%LOCALAPPDATA%\MicroCompta\microcompta.duckdb` |
| Factures, justificatifs et exports | `%LOCALAPPDATA%\MicroCompta\documents\<année>\<type>\` |
| Votre accès à Google Drive et votre clé Stripe | `%LOCALAPPDATA%\MicroCompta\secrets\` |
| Le journal de l'application | `%LOCALAPPDATA%\MicroCompta\logs\` |

`%LOCALAPPDATA%` désigne votre dossier `C:\Users\<votre nom>\AppData\Local`. Pour l'ouvrir,
tapez `%LOCALAPPDATA%\MicroCompta` dans la barre d'adresse de l'Explorateur de fichiers.

Ce dossier est séparé de celui de l'application. Mettre à jour, déplacer ou supprimer le dossier
de l'application ne touche donc pas vos registres.

## Quitter l'application

Fermer la fenêtre ne quitte pas l'application : elle reste active dans la zone de notification,
en bas à droite de l'écran, pour envoyer les rappels d'échéance. Sous Windows 11, son icône est
parfois cachée derrière la petite flèche « ^ » de cette zone. Pour quitter, faites un clic droit
sur l'icône, puis « Quitter MicroCompta ».

## Mettre à jour

1. Quittez l'application comme décrit ci-dessus.
2. Remplacez les fichiers du dossier de l'application par ceux de la nouvelle version, en gardant
   le même dossier. Avec git, un `git pull` suffit.
3. Supprimez le fichier `.venv\.deps-ok`. Tant que ce fichier existe, `run.bat` considère que les
   bibliothèques sont installées et ne les vérifie plus.
4. Double-cliquez sur `run.bat`, et non sur le raccourci : le raccourci ouvre l'application
   directement, sans passer par l'installation. `run.bat` installe ce qui manque, puis ouvre
   l'application. Quand rien n'a changé, cette étape ne fait que vérifier.

## Déplacer le dossier de l'application

Les raccourcis contiennent le chemin complet du dossier, donc ils ne marchent plus après un
déplacement. Supprimez `MicroCompta.lnk` dans le dossier de l'application, puis relancez
`run.bat`. Il recrée le raccourci du dossier et remplace ceux du Bureau et du menu Démarrer.

Si vous aviez demandé le lancement avec Windows, recréez aussi ce raccourci-là, sinon les rappels
s'arrêtent sans prévenir. Le guide des [raccourcis Windows](raccourci-windows.md) donne la
commande.

## Désinstaller

1. Quittez l'application.
2. Supprimez les raccourcis du Bureau, du menu Démarrer et, si vous l'aviez créé, du démarrage
   automatique. Le guide des [raccourcis Windows](raccourci-windows.md) indique où les trouver.
3. Supprimez le dossier de l'application.

Vos registres restent dans `%LOCALAPPDATA%\MicroCompta`. Ce sont vos documents comptables, à
conserver. Ne supprimez ce dossier que si vous en gardez une copie ailleurs, et après avoir
vérifié qu'elle s'ouvre.

## Si quelque chose bloque

| Ce que vous voyez | Ce qu'il faut faire |
| --- | --- |
| « Setup failed », avec une mention de Python | Installez Python 3.11 ou plus récent en cochant « Add python.exe to PATH », puis relancez `run.bat`. |
| « Setup failed », avec une mention de « long path » | Déplacez le dossier vers un chemin plus court, comme `C:\MicroCompta`, puis relancez `run.bat`. |
| Le raccourci ramène la fenêtre déjà ouverte au lieu d'en ouvrir une autre | C'est voulu. Une seule copie peut tourner à la fois, et un nouveau lancement ramène celle qui tourne. |
| Une fenêtre « MicroCompta ne peut pas démarrer » | Le message donne la cause. Le détail est dans le dossier `logs` cité plus haut. |

Pour signaler un problème, ouvrez une « issue » sur la page GitHub du projet, onglet « Issues ».

## Préparer l'environnement sans ouvrir l'application

Ouvrez le dossier de l'application dans l'Explorateur, cliquez dans la barre d'adresse, tapez
`cmd` et appuyez sur Entrée. Dans la fenêtre qui s'ouvre, tapez :

```bash
run.bat --setup
```

Cette commande installe tout puis s'arrête, sans lancer l'application. Elle sert à préparer une
machine à l'avance, ou à installer avant une restauration depuis Google Drive.
