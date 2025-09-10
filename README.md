# ssh-du-dashboard

Petit tableau de bord qui se connecte en SSH à une liste `user@host` et affiche une *arborescence* (profondeur configurable) et la *taille utilisée* du HOME de l'utilisateur.

## Démarrage rapide

1. Télécharge l'archive et décompresse-la.
2. Édite `hosts.txt` et ajoute une ligne par cible, ex. :
   ```
   teqtelapiphoneportal@46.28.168.118  Production PPE
   ```
3. Assure-toi d'avoir une clé privée SSH (ex: `~/.ssh/id_rsa`) avec les accès aux cibles.
   - `chmod 600 ~/.ssh/id_rsa`
4. Lance :
   ```bash
   docker compose up -d --build
   ```
5. Ouvre http://localhost:9090 et clique **Scanner maintenant**.

## Variables d'environnement (docker-compose.yml)

- `HOSTS_FILE=/data/hosts.txt` — fichier des cibles monté en RO.
- `SSH_KEY=/ssh/id_rsa` — chemin de la clé privée (montée en RO).
- `DEPTH=2` — profondeur de l'arborescence.
- `CONNECT_TIMEOUT=8` — timeout de connexion SSH (s).
- `CMD_TIMEOUT=60` — timeout de la commande distante (s).
- `PORT=9090` — port HTTP du conteneur.

## Sécurité

- La clé privée **n'est pas copiée** dans l'image, elle est **montée en read-only**.
- `StrictHostKeyChecking=no` est activé pour éviter les prompts. Si tu veux sécuriser, monte aussi un `known_hosts`.
- Les commandes exécutées sont en lecture seule (`du`, `find`, `hostname`).

## Notes

- Si `du --max-depth` n'existe pas sur la cible (BusyBox), fallback via `find`.
- Pour des arbres plus profonds, augmente `DEPTH` (attention au temps de scan).
- Si le HOME détecté termine par `/home/<user>` (ex. ISPConfig), le script remonte automatiquement de deux répertoires pour analyser le bon dossier.
