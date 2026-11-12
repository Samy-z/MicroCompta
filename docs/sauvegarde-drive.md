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

Les noms de menus ci-dessous sont ceux de la console Google en anglais. Si elle s'affiche en
français, ils sont traduits, par exemple « Bibliothèque » pour « Library ».

1. Ouvrez la [console Google Cloud](https://console.cloud.google.com/) et créez un projet, par
   exemple « MicroCompta ».
2. Dans « APIs & Services », puis « Library », activez « Google Drive API ».
3. Dans « Google Auth Platform », indiquez le nom de l'application et votre adresse e-mail.
   Choisissez l'audience « External ».
4. Sur la page « Audience » de « Google Auth Platform », publiez l'application pour que son état
   passe à « In production ». Tant qu'elle reste en « Testing », Google annule la connexion tous
   les 7 jours, et la sauvegarde s'arrête jusqu'à ce que vous vous reconnectiez.
5. Dans « Clients », choisissez « Create client », de type « Desktop app », puis téléchargez le
   fichier JSON proposé.
6. Dans MicroCompta, page Sauvegarde, cliquez sur « Choisir le fichier client… » et choisissez ce
   fichier JSON. Cliquez ensuite sur « Se connecter avec Google ».

Votre navigateur s'ouvre sur la page de connexion Google. Comme votre application n'est pas
vérifiée par Google, un avertissement peut apparaître : il concerne l'application que vous venez
de créer vous-même. Ouvrez le lien des paramètres avancés, puis celui qui mène à votre
application. Sur l'écran suivant, cochez la case qui autorise l'accès à Drive.

Après la connexion, Google remet un jeton, une clé que l'application présente à chaque envoi.
L'application garde une copie de ce jeton et du fichier client dans
`%LOCALAPPDATA%\MicroCompta\secrets`, hors du dossier de l'application. Toute personne qui a
accès à votre session Windows peut lire ce dossier, comme vos autres fichiers. Le fichier JSON
téléchargé peut ensuite être supprimé.

« Se déconnecter » oublie le jeton sur cet ordinateur et ne change rien dans Drive. Pour retirer
définitivement l'accès de l'application, passez par la page de sécurité de votre compte Google.

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
