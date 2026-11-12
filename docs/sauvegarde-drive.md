# La sauvegarde Google Drive

MicroCompta peut envoyer une copie de chaque document dans votre propre Google Drive. Ce guide
vous accompagne pour brancher votre compte, une seule fois. Il explique aussi ce qui est envoyé,
comment sauvegarder sans Drive et comment tout récupérer sans l'application.

L'application fonctionne entièrement sans connexion. Tant que Drive n'est pas branché ou que vous
êtes hors ligne, les documents attendent dans une file d'envoi, qui reprend dès que c'est
possible.

## Brancher votre compte

Vous créez un accès à Google réservé à votre usage, appelé « client OAuth » : c'est lui qui
permet à l'application de déposer des fichiers dans votre Drive. L'application ne voit jamais
votre mot de passe Google. Elle ne demande que l'autorisation `drive.file`, qui lui permet de voir
uniquement les fichiers qu'elle a créés.

Chaque étape renvoie directement à la bonne page de la console Google Cloud. Vérifiez en haut de
la page que c'est bien votre projet MicroCompta qui est sélectionné.

1. [Créez un projet](https://console.cloud.google.com/projectcreate), par exemple « MicroCompta ».
2. [Activez Google Drive API](https://console.cloud.google.com/apis/library/drive.googleapis.com)
   pour ce projet.
3. [Configurez Google Auth Platform](https://console.cloud.google.com/auth/overview/create) :
   indiquez le nom de l'application, une adresse e-mail d'assistance, l'audience « Externe » et
   une adresse de contact.
4. Sur la page [Branding](https://console.cloud.google.com/auth/branding), renseignez la page
   d'accueil de l'application et le lien vers ses règles de confidentialité. Pour MicroCompta, la
   page d'accueil est l'adresse de la page GitHub du projet, et les règles de confidentialité sont
   la page [docs/confidentialite.md](confidentialite.md) de ce même projet sur GitHub. Si la
   console vous demande d'ajouter leur domaine aux domaines autorisés, ajoutez `github.com`.
   Enregistrez.
5. Sur la page [Audience](https://console.cloud.google.com/auth/audience), cliquez sur « Publier
   l'application » et confirmez : l'état passe de « Test » à « En production ». Le bouton reste
   grisé tant que l'étape 4 n'est pas faite. MicroCompta ne demande qu'une autorisation que
   Google ne classe pas comme sensible, donc la validation de l'application par Google n'est pas
   obligatoire.
6. [Créez un client](https://console.cloud.google.com/auth/clients/create) de type « Application
   de bureau », puis téléchargez le fichier JSON proposé.
7. Dans MicroCompta, page Sauvegarde, cliquez sur « Choisir le fichier client… » et choisissez ce
   fichier JSON. Cliquez ensuite sur « Se connecter avec Google ».

Votre navigateur s'ouvre sur la page de connexion Google. Choisissez votre compte, puis autorisez
l'accès à Drive.

Si Google affiche « Accès bloqué : MicroCompta n'a pas terminé la procédure de validation de
Google » avec l'erreur 403, l'application est encore à l'état « Test ». Dans cet état, seules les
adresses listées dans « Utilisateurs tests », sur la page Audience, peuvent se connecter. Publier
l'application règle le problème. Ajouter votre adresse aux utilisateurs tests permet aussi
d'essayer tout de suite, mais Google annule alors la connexion 7 jours après chaque autorisation,
et la sauvegarde s'arrête jusqu'à la suivante.

Après la connexion, Google remet un jeton, une clé que l'application présente à chaque envoi.
L'application garde une copie de ce jeton et du fichier client dans
`%LOCALAPPDATA%\MicroCompta\secrets`, hors du dossier de l'application. Toute personne qui a
accès à votre session Windows peut lire ce dossier, comme vos autres fichiers. Le fichier JSON
téléchargé peut ensuite être supprimé.

« Se déconnecter » oublie le jeton sur cet ordinateur et ne change rien dans Drive. Pour retirer
définitivement l'accès de l'application, passez par la page
[Applications tierces](https://myaccount.google.com/connections) de votre compte Google. Les
[règles de confidentialité](confidentialite.md) détaillent ce que l'application fait de cet accès.

Une fois branché, ouvrez dans Drive un des fichiers envoyés pour vérifier qu'il s'ouvre bien. La
liste de contrôle de la page Revue annuelle vous le redemande chaque année.

## Ce qui est envoyé, et où

| Document | Quand | Dossier dans Drive |
| --- | --- | --- |
| Factures et factures d'avoir en PDF | À l'émission | `MicroCompta/<année>/factures/` |
| Justificatifs joints à un paiement | Quand vous les joignez | `MicroCompta/<année>/recus/` |
| Justificatifs joints à un achat | Quand vous les joignez | `MicroCompta/<année>/achats/` |
| Exports CSV et PDF | À l'export | `MicroCompta/<année>/exports/` |
| Copie compressée des registres, avec les exports CSV du livre des recettes, des factures et des achats | Quelques minutes après un changement, chaque heure si quelque chose a changé, et quand vous quittez l'application | `MicroCompta/<année>/sauvegardes/` |

Un document ne compte comme envoyé que si Drive renvoie la même empreinte que le fichier local.
Une empreinte est un résumé calculé à partir du contenu d'un fichier : deux fichiers identiques
ont la même. La page Sauvegarde affiche l'état de chaque document :

- **en attente** : le document attend une connexion ou une reconnexion. Être hors ligne ne compte
  jamais comme un échec. Les nouvelles tentatives s'espacent d'une minute à une heure.
- **envoyé** : Drive a confirmé la même empreinte.
- **en échec** : quelque chose doit être regardé, et la raison est affichée. L'application
  réessaie toutes les 6 heures, ou tout de suite avec « Réessayer ».

Le code qui parle à Drive n'a aucune commande de suppression ni de mise à la corbeille, et des
tests vérifient qu'il refuse toute adresse qui n'est pas celle de Google. Si une empreinte ne
correspond pas, l'envoi recommence.

## Sauvegarder sans Drive

Tout ce que l'application enregistre se trouve dans `%LOCALAPPDATA%\MicroCompta`. Sans Drive,
quittez l'application, puis copiez ce dossier entier sur un disque externe ou une clé USB. Quitter
d'abord compte : tant que l'application tourne, Windows refuse de copier la base de données.

## Récupérer vos données sans l'application

Les fichiers CSV s'ouvrent dans n'importe quel tableur. Ils utilisent le point-virgule comme
séparateur, la virgule décimale et l'encodage UTF-8.

La copie des registres est une base DuckDB compressée en ZIP. DuckDB est le petit moteur de base
de données qu'utilise l'application. Avec Python, une fois la bibliothèque installée par
`pip install duckdb`, cette commande affiche le livre des recettes d'une copie décompressée :

```bash
python -c "import duckdb; print(duckdb.connect('microcompta.duckdb', read_only=True).sql('SELECT * FROM ledger'))"
```

## Restaurer sur un nouvel ordinateur

1. Installez l'application avec `run.bat --setup`, qui installe sans lancer. Le
   [guide d'installation](installation.md#préparer-lenvironnement-sans-ouvrir-lapplication)
   explique où taper cette commande.
2. Décompressez la copie des registres en `%LOCALAPPDATA%\MicroCompta\microcompta.duckdb`.
3. Recopiez les documents dans `%LOCALAPPDATA%\MicroCompta\documents\`, rangés par année puis par
   type, comme dans Drive. Sans eux, la vérification d'intégrité signale les factures dont le
   fichier manque.
4. Double-cliquez sur `run.bat` : il crée les raccourcis, que `--setup` n'a pas faits, puis lance
   l'application.
