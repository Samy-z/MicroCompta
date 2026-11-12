# Guide d'utilisation

Ce guide s'adresse à vous, micro-entrepreneur, une fois l'[installation](installation.md) faite.
Il décrit chaque page de l'application et ce que vous y faites. Les termes officiels sont
expliqués à leur première apparition, et le [glossaire](glossaire.md) les reprend avec leurs
sources.

## La fenêtre

La barre de gauche donne accès aux huit pages : Seuils, Recettes, Dépenses, Clients, Factures,
Échéances, Revue annuelle et Sauvegarde. Une pastille de couleur sur une page signale quelque
chose à faire, par exemple le nombre d'échéances en retard.

À côté, le volet « Saisir un encaissement » sert à enregistrer chaque paiement reçu. Le bouton
« ‹‹ » en haut du volet le replie pour laisser plus de place aux tableaux, et un clic sur la
bande verticale le rouvre.

En haut à droite, l'engrenage ouvre les Paramètres et « Aide » résume le fonctionnement de
l'application. En bas, la barre d'état donne le résultat de la dernière action et l'état de la
sauvegarde vers Google Drive.

Gardez la souris sur un nombre, un bouton ou un champ pour voir une bulle qui explique ce qu'il
représente. Au clavier, la touche Tab sur une carte de chiffres affiche la même bulle.

## Saisir un encaissement

Prenons un exemple tiré des données de démonstration. Le 30 octobre 2026, votre client
américain vous paie 1 020 $ par Stripe. Stripe garde 29,88 $ et votre banque reçoit 910,26 €.

Remplissez le volet ainsi :

| Champ | Ce que vous saisissez |
| --- | --- |
| Encaissé le | Le jour où l'argent est arrivé : 30/10/2026. Le chiffre d'affaires compte à cette date, pas à celle de la facture. |
| Client | Le client qui a payé. Le bouton « + » à côté en ajoute un nouveau sans quitter le volet. |
| Désignation | Ce que le paiement règle, par exemple « Annotation, semaine 44 ». Le livre des recettes doit indiquer l'origine de chaque recette. |
| Mode | Stripe, PayPal, virement bancaire ou autre. |
| Référence | La référence du paiement chez Stripe ou PayPal. La même référence ne peut pas être enregistrée deux fois pour un client, ce qui évite les doublons. |
| Brut | Ce que le client a payé, avant frais, dans sa devise : 1 020. |
| Taux pour 1 EUR | Le nombre de dollars pour 1 euro ce jour-là, publié par la Banque centrale européenne (BCE) sur sa [page des taux de référence](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html) : 1,0823. Pour un client payé en euros, le taux reste à 1. |
| Source du taux | D'où vient le taux. La référence BCE est proposée par défaut. |
| Frais du prestataire | Ce que le service de paiement, Stripe ou PayPal, a gardé, et dans quelle devise : 29,88 USD. |
| Net crédité | Ce qui est arrivé sur votre compte : 910,26 EUR. |

Le volet calcule le brut en euros, 942,44 €, et les cotisations de ce paiement au taux du jour,
180,95 €. Cliquez sur « Enregistrer le paiement », vérifiez le résumé, puis confirmez. Vous pouvez saisir un
paiement passé en choisissant sa date ; une date dans le futur est refusée. Le
bouton « Joindre un justificatif… » ajoute un fichier, comme le reçu Stripe, avant
l'enregistrement.

## Corriger une erreur

Une écriture enregistrée ne se modifie plus. C'est la règle d'un registre comptable : chaque
correction doit rester visible.

Pour corriger un paiement, ouvrez la page Recettes, sélectionnez la ligne, puis cliquez sur
« Annuler l'écriture… ». Indiquez la raison. L'application ajoute une écriture d'annulation aux
montants opposés, puis vous saisissez le bon paiement. Le registre des achats fonctionne de la
même façon.

## Les pages

### Seuils

Cette page montre votre année d'un coup d'œil. La grande tuile donne le cumul de l'année, la
projection jusqu'au 31 décembre au même rythme, la part du seuil micro déjà atteinte et le
bénéfice imposable indicatif, c'est-à-dire le chiffre d'affaires moins l'abattement forfaitaire.
L'abattement forfaitaire est la part du chiffre d'affaires que l'administration retire pour tenir
lieu de toutes vos charges. Les tuiles voisines donnent les cotisations de l'année, le taux en
vigueur et la prochaine échéance.

Quatre cartes suivent chacune un seuil :

- **Seuil du régime micro** : le chiffre d'affaires maximal du régime, réduit au prorata la
  première année. Le dépasser une année est permis ; deux années de suite font sortir du régime
  au 1er janvier.
- **Franchise en base de TVA** : le régime qui vous dispense de facturer la TVA. Au-delà du seuil
  de franchise, elle prend fin au 1er janvier suivant ; au-delà du seuil majoré, dès le
  dépassement. Seul compte le chiffre d'affaires imposable en France.
- **Compte bancaire dédié** : un compte réservé à l'activité devient obligatoire après deux
  années de suite au-dessus de son seuil.
- **CFE** : la cotisation foncière des entreprises, un impôt local. La carte rappelle les cas
  d'exonération qui vous concernent, comme l'année de la création.

Sur chaque barre, la partie pleine est le montant atteint et la partie pâle la projection. Le
trait blanc marque le seuil, et un trait gris un seuil inférieur, comme le seuil de franchise
sous le seuil majoré. En bas, deux tableaux donnent
les cotisations par période de déclaration et les prochaines échéances.

### Recettes

Le livre des recettes est la liste datée de vos encaissements que la loi vous impose de tenir,
avec une ligne par paiement. Les cartes du haut donnent les totaux de chaque trimestre et de
l'année, le brut en euros, les frais des services de paiement et les cotisations.

Les boutons servent à annuler une écriture, à joindre un justificatif à la ligne sélectionnée et
à exporter l'année en CSV, pour un tableur, ou en PDF. Les exports des registres sont toujours en
français, car ce sont des documents légaux.

### Dépenses

Le registre des achats : ce que vous achetez pour l'activité, en euros, TVA comprise. En
franchise en base de TVA, la TVA de vos achats n'est pas récupérable, d'où le montant TTC.

Pour chaque achat, vous indiquez la date de paiement, le fournisseur, la désignation, la nature,
le montant, la part professionnelle et le mode de paiement. La part professionnelle sert aux
dépenses mixtes : un abonnement de transport utilisé à moitié pour l'activité se saisit à 50 %.
Un équipement durable de plus de 500 € hors taxes (HT), comme un ordinateur, se range en
« Immobilisation » ; en dessous, il va en « Petit matériel ».

« Dupliquer… » reprend l'achat sélectionné à la date du jour, ce qui évite de tout ressaisir pour
un abonnement mensuel. Les boutons d'annulation, de justificatif et d'export fonctionnent comme
sur la page Recettes.

En régime micro, vos dépenses ne réduisent ni le chiffre d'affaires, ni les cotisations, ni
l'impôt : l'abattement forfaitaire en tient lieu. Ce registre ne change donc aucun autre chiffre
de l'application.

La page compare tout de même l'abattement forfaitaire à vos charges réelles estimées. Cette
comparaison éclaire le choix entre le régime micro et le régime réel, où l'impôt se calcule sur
les charges réelles. Ce n'est qu'un repère, qui ne regarde que l'impôt sur le revenu.

### Clients

La liste des personnes que vous facturez. « Ajouter un client… » et « Modifier… » ouvrent la même
fenêtre que le bouton « + » du volet de saisie.

La case « Imposable en France » décide si le chiffre d'affaires de ce client compte pour la
franchise en base de TVA. Cochez-la pour un client en France. Elle est décochée à la création,
car le cas visé au départ est un client professionnel hors Union européenne, probablement exclu
de ce calcul ; le service des impôts doit encore le confirmer. Décochez
« Actif » pour un ancien client : il disparaît du volet de saisie, mais ses écritures restent.

Modifier un client ne change ni les factures émises ni les écritures : chacune garde les
informations du jour de son enregistrement.

### Factures

Une facture récapitule les paiements d'un mois pour un client. En haut de la page, choisissez le
client et le mois après « Nouveau brouillon mensuel : », puis cliquez sur « Créer le brouillon ».

Un brouillon se modifie librement avec « Modifier… » : dates de la prestation, lignes, quantités
et mention libre. « Aperçu » montre le PDF, et « Supprimer le brouillon » l'efface. Un brouillon
ne prend pas de numéro.

« Émettre… » transforme le brouillon en facture définitive. Il faut alors avoir saisi dans les
Paramètres un SIREN valide, le numéro à 9 chiffres de votre entreprise. Pour une facture en dollars, vous saisissez le taux BCE du jour d'émission et sa date
de publication, et la facture affiche le montant, sa contre-valeur en euros et le taux appliqué.
La facture prend le numéro suivant, par exemple `FA-2027-0012`, sans trou d'une facture à
l'autre ni d'une année à l'autre. Le PDF est enregistré et part vers Drive.

Une facture émise ne se modifie plus. Pour la corriger, « Facture d'avoir… » émet un document qui
l'annule, avec son propre numéro, par exemple `AV-2027-0013`. Si vous annulez un paiement qui
figurait sur une facture émise, la page Factures porte une pastille « à corriger » jusqu'à la
facture d'avoir.

Le taux d'une facture et celui du livre des recettes sont distincts. La facture utilise le taux
BCE de son jour d'émission ; le chiffre d'affaires utilise le taux de chaque paiement, au jour
où il est arrivé. La page affiche les deux montants quand ils diffèrent.

### Échéances

Les déclarations et autres dates, calculées depuis votre date de début d'activité et votre
rythme de déclaration. On y trouve les déclarations de chiffre d'affaires à l'URSSAF, l'organisme
qui collecte vos cotisations, à faire même à zéro avec la mention « Néant ». S'y ajoutent la
déclaration initiale de CFE et la déclaration complémentaire 2042-C-PRO, où reporter votre
chiffre d'affaires avec vos revenus. La page donne aussi la date limite de l'option pour le
versement libératoire, qui permet de régler l'impôt sur le revenu avec les cotisations.

Sélectionnez une ligne et cliquez sur « Marquer comme fait » une fois la démarche accomplie.
Certaines dates ne sont publiées qu'au printemps, comme celle de la 2042-C-PRO : « Indiquer la
date… » permet de la saisir quand vous la connaissez. La case « Afficher faites et passées »
montre aussi les échéances terminées.

### Revue annuelle

Une page à ouvrir en fin d'année. Elle donne le chiffre d'affaires, les cotisations, le montant à
reporter sur la déclaration 2042-C-PRO, le bénéfice imposable indicatif et la projection.
Viennent ensuite les totaux tous les 3 mois et une liste de contrôle à cocher.

Le tableau « Reste à confirmer » liste les questions que les sources officielles ne tranchent
pas encore. La dernière section de ce guide les reprend.

### Sauvegarde

L'état de chaque document envoyé vers Google Drive : en attente, envoyé ou en échec, avec la
raison. « Envoyer maintenant » lance un envoi, « Réessayer » relance ceux en échec et
« Sauvegarder les données » fait une copie immédiate des registres. Le
[guide de la sauvegarde](sauvegarde-drive.md) explique comment brancher votre compte Google.

## Les Paramètres

L'engrenage en haut à droite ouvre deux pages.

« Identité et activité » contient ce qui est imprimé sur les factures, votre activité et le
réglage de l'application. L'activité comprend la date de début, le type d'activité et le rythme
des déclarations, mensuel ou trimestriel. On y coche aussi l'ACRE, la réduction de cotisations
des créateurs, et le versement libératoire, une option qui règle l'impôt sur le revenu avec les
cotisations. La même page règle la langue, les jours de rappel avant une échéance et deux choix
sur le chiffre d'affaires encore à confirmer par l'URSSAF.

« Barèmes » liste chaque taux, seuil et date fixe utilisé par l'application, avec sa source. Pour
changer une valeur à partir d'une date, sélectionnez la ligne et cliquez sur « Nouvelle
valeur… ». Les dates antérieures gardent l'ancienne valeur, donc les années passées ne changent
pas. Une échéance annuelle vous rappelle de revérifier ces barèmes.

## Les rappels

Les rappels d'échéance s'affichent dans la zone de notification de Windows, en bas à droite de
l'écran. Par défaut, ils arrivent 14, 7, 3 et 1 jours avant chaque date.

Ils ne partent que si l'application tourne. Fermer la fenêtre la garde donc active dans la zone
de notification ; pour la quitter vraiment, faites un clic droit sur son icône puis « Quitter MicroCompta ».
Pour qu'elle démarre avec Windows, voyez les [raccourcis Windows](raccourci-windows.md).

## Raccourcis clavier

| Touches | Effet |
| --- | --- |
| Ctrl+1 à Ctrl+8 | Ouvrir la page correspondante, de Seuils à Sauvegarde |
| Ctrl+B | Replier ou rouvrir le volet de saisie |
| Ctrl+, | Ouvrir les Paramètres |
| Ctrl+U | Envoyer maintenant vers Google Drive |
| F1 | Afficher l'aide |
| Ctrl+C | Copier la ligne sélectionnée d'un tableau |

## La langue

L'application démarre en français. L'anglais se choisit dans les Paramètres et s'applique tout de
suite. Les factures, les factures d'avoir et les exports des registres restent en français dans tous
les cas, car ce sont des documents légaux français.

## Ce qui reste à confirmer

Les sources officielles consultées ne tranchent pas les questions suivantes. L'application les
signale là où elles comptent. Les deux choix sur le chiffre d'affaires se changent dans les
Paramètres, et la case « Imposable en France » sur chaque client.

| Question | Qui répond | Ce que fait l'application |
| --- | --- | --- |
| Quel taux de change retenir pour le chiffre d'affaires en dollars | URSSAF | Le taux saisi sur chaque écriture, BCE par défaut |
| Chiffre d'affaires avant ou après les frais du prestataire | URSSAF | Avant frais par défaut. La fiche F23257 dit qu'aucune commission n'est déduite, sans citer Stripe ni PayPal. |
| Un client professionnel hors UE compte-t-il pour la franchise de TVA ? | Service des impôts des entreprises (SIE) | Exclu par défaut, case par client |
| Faut-il une mention de facture en plus de « TVA non applicable, art. 293 B du CGI » pour ce client ? Le CGI est le Code général des impôts. | SIE | Mention modifiable dans les Paramètres |
| Versement libératoire sans revenu fiscal de référence français | SIE | Un rappel seulement |
| L'ACRE réduit-elle la part du versement libératoire ? | URSSAF | Suppose que non |
| La contribution à la formation professionnelle s'ajoute-t-elle au taux ? | URSSAF | Suppose que non, d'après la fiche F36232 |
| Une première année au prorata compte-t-elle comme une année de dépassement ? | URSSAF ou SIE | La compte, et le signale |
| Que faire de la TVA d'un abonnement acheté à une entreprise étrangère ? | SIE | Listé dans l'application |
| Date limite pour opter pour un régime réel en activité libérale | SIE | Listé dans l'application ; les sources se contredisent |
