# Règles de confidentialité de MicroCompta

MicroCompta est une application de bureau gratuite et open source qui tient la comptabilité d'un
micro-entrepreneur sur son propre ordinateur. Cette page explique quelles données elle utilise et
où elles vont. Elle sert aussi de page de règles de confidentialité pour l'accès à Google Drive.

## Ce que l'application garde, et où

Vos registres, vos documents et vos réglages restent sur votre ordinateur, dans le dossier
`%LOCALAPPDATA%\MicroCompta`. Le développeur de MicroCompta n'exploite aucun serveur et ne reçoit
aucune de vos données. L'application ne contient ni publicité ni mesure d'audience.

## Ce qu'elle fait avec votre compte Google

Si vous branchez la sauvegarde, l'application demande à Google une seule autorisation,
`drive.file`. Elle ne peut alors voir et modifier que les fichiers qu'elle a elle-même créés dans
votre Drive, et aucun autre.

Elle s'en sert uniquement pour déposer une copie de vos factures, justificatifs, exports et
registres dans un dossier `MicroCompta` de votre Drive. Elle relit ensuite l'empreinte de chaque
fichier envoyé, pour vérifier qu'il est arrivé intact. Elle ne supprime aucun fichier et ne
partage rien.

Après votre connexion, Google remet un jeton, une clé qui permet ces envois. Il est enregistré sur
votre ordinateur, dans `%LOCALAPPDATA%\MicroCompta\secrets`, et n'est envoyé qu'à Google.

Les données obtenues par les API de Google ne sont transmises à personne, ne servent à aucune
publicité et ne servent à entraîner aucun modèle d'intelligence artificielle. Leur utilisation
respecte la
[Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy),
y compris ses exigences d'utilisation limitée.

## Retirer l'accès

Dans l'application, page Sauvegarde, « Se déconnecter » efface le jeton de votre ordinateur. Pour
retirer l'accès côté Google, passez par la page
[Applications tierces](https://myaccount.google.com/connections) de votre compte Google. Les
fichiers déjà envoyés restent dans votre Drive, où vous pouvez les supprimer vous-même.

## Contact

Pour toute question, ouvrez une « issue » sur la page GitHub du projet.

Dernière mise à jour : 12 novembre 2026.
