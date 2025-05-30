
.. index:: SmartHomeNG als Dienst

.. role:: bluesup
.. role:: redsup

========================================
SmartHomeNG als Dienst :bluesup:`update`
========================================

.. contents:: Schritte der Installation
   :local:

|

Einrechten des Dienstes
=======================

Um SmartHomeNG auf einer älteren Version als Debian 12 (bookworm) als Dienst zu betreiben muss eine Startup-Datei
für **systemd** erstellt werden. Für Debiam 12 oder neuer, bitte der Beschreibung im folgenden Abschnitt
(Nutzung eines virtuellen Environments) folgen.

.. warning::
    Bevor man als **Neuling** SmartHomeNG als Dienst einrichtet,
    sollte man das System verstanden haben und es sollte
    fehlerfrei laufen.

Zum Einrichten den Texteditor starten mit

.. code-block:: bash

   sudo nano /etc/systemd/system/smarthome.service

und folgenden Text hineinkopieren:

.. code-block:: bash

   [Unit]
   Description=SmartHomeNG daemon
   After=network-online.target
   After=knxd.service
   After=knxd.socket

   [Service]
   Type=forking
   ExecStart=/usr/bin/python3 /usr/local/smarthome/bin/smarthome.py
   WorkingDirectory=/usr/local/smarthome
   User=smarthome
   PIDFile=/usr/local/smarthome/var/run/smarthome.pid
   Restart=on-failure
   TimeoutStartSec=900
   RestartForceExitStatus=5

   [Install]
   WantedBy=default.target

.. attention::

   Die Angabe **RestartForceExitStatus=5** ist notwendig, damit der automatische Restart bei der Nachinstallation
   von Python Packages und der durch die AdminGUI ausgelöste Neustart auch für ein als Service laufendes SmartHomeNG
   funktionieren.

|

Nutzung eines virtuellen Environments :redsup:`neu`
===================================================

Bei der Installation von SmartHomeNG v1.10 (oder neuer) wird vom postinstall-Skript ein virtuelles Python
Environment angelegt. Wenn dieses virtuelle Environment im Zusammenhang mit dem Dienst genutzt werden soll, muss
der Python Interpreter aus diesem virtuellen Environment genutzt werden um SmartHomeNG zu betreiben.
Dazu muss der folgende Text in die Datei /etc/systemd/system/smarthome.service eingefügt werden:

.. code-block:: bash

   [Unit]
   Description=SmartHomeNG daemon
   After=network.target
   After=knxd.service
   After=knxd.socket

   [Service]
   Type=forking
   ExecStart=/usr/local/smarthome/venvs/py_shng/bin/python3 /usr/local/smarthome/bin/smarthome.py
   WorkingDirectory=/usr/local/smarthome
   User=smarthome
   PIDFile=/usr/local/smarthome/var/run/smarthome.pid
   Restart=on-failure
   TimeoutStartSec=900
   RestartForceExitStatus=5

   [Install]
   WantedBy=default.target

Der Unterschied zur bisherigen Version liegt im Eintrag **ExecStart**

|

Starten des Dienstes
====================

Der so vorbereitete Dienst kann über den **systemctl** Befehl gestartet
werden.

.. code-block:: bash

   sudo systemctl start smarthome.service

Im Log schauen, ob keine Fehlermeldung beim Starten geschrieben wurde.

.. code-block:: bash

   tail /usr/local/smarthome/var/log/smarthome-warnings.log

Wenn alles ok ist, kann der Autostart aktiviert werden:

.. code-block:: bash

   sudo systemctl enable smarthome.service

Bei Systemstart wird nun SmartHomeNG automatisch gestartet.

Um den Dienst wieder auszuschalten und den Neustart bei Systemstart zu
verhindern nutzt man:

.. code-block:: bash

   sudo systemctl disable smarthome.service

Um zu sehen, ob SmartHomeNG läuft, genügt ein

.. code-block:: bash

   sudo systemctl status smarthome.service

Läuft es noch nicht und man möchte sozusagen manuell starten reicht ein:

.. code-block:: bash

   sudo systemctl start smarthome.service

Ein Neustart von SmartHomeNG würde mit

.. code-block:: bash

   sudo systemctl restart smarthome.service

funktionieren, ein Stop von SmartHomeNG entsprechend

.. code-block:: bash

   sudo systemctl stop smarthome.service
