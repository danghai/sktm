sktm - skt manager
==================

[![Travis CI Build Status][travis_badge]][travis_page]
[![Test Coverage Status][coveralls_badge]][coveralls_page]

sktm is an orchestrator for skt keeping track of known baselines and tested
patches.

Prerequisites
-------------

NOTE: The instructions below are intended for Fedora Server 28 and will work
with minimal install.

Sktm uses Jenkins to queue and execute jobs. You can install and start latest
Jenkins like this:

    sudo curl -o /etc/yum.repos.d/jenkins.repo \
                 https://pkg.jenkins.io/redhat/jenkins.repo
    sudo rpm --import https://pkg.jenkins.io/redhat/jenkins.io.key
    sudo dnf install -y java jenkins
    sudo systemctl enable jenkins

Latest versions of Fedora have Java versions with tightened-down encryption
algorithm requirements, which Jenkins code and infrastructure do not yet meet.
Until those are updated, you will need to relax the requirements for Jenkins:

    sudo tee /var/lib/jenkins/java.security >/dev/null <<"EOF"
    jdk.certpath.disabledAlgorithms=MD2, MD5, SHA1 jdkCA & usage TLSServer, \
        RSA keySize < 1023, DSA keySize < 1024, EC keySize < 224
    EOF

    sudo sed -i /etc/sysconfig/jenkins \
             -e '/^JENKINS_JAVA_OPTIONS=/ s%"$% -Djava.security.properties=/var/lib/jenkins/java.security"%'

Start Jenkins:

    sudo systemctl start jenkins

From now on the documentation assumes Jenkins is serving HTTP requests on the
default URL of http://localhost:8080/.

Make sure you have Python 2 installed to be able to run sktm:

    sudo dnf install -y python2

Install sktm requirements:

    sudo pip2 install dateutils enum34 jenkinsapi junit_xml requests

Install Jenkins Job Builder to be able to automate Jenkins setup:

    sudo pip2 install jenkins-job-builder

Install Python's `virtualenv` to be able to run `skt` within Jenkins jobs:

    sudo pip2 install virtualenv

Install and start `sendmail` to allow `skt` to send report messages:

    sudo dnf install -y sendmail
    sudo systemctl enable --now sendmail

Install Kerberos client to enable `skt` authentication to Beaker:

    sudo dnf install -y krb5-workstation

Install `skt` dependencies following its
[README.md](https://github.com/RH-FMK/skt).

Setup
-----

### Beaker access

You will need access to a Beaker instance configured for the `jenkins`
user. First, create the Beaker client's configuration directory:

    sudo -u jenkins mkdir -p ~jenkins/.beaker_client

Then you can setup Kerberos authentication to Beaker like this:

    sudo -u jenkins tee ~jenkins/.beaker_client/config >/dev/null <<"EOF"
    HUB_URL = "<BEAKER_URL>"
    AUTH_METHOD = "krbv"
    KRB_REALM = "<KERBEROS_REALM>"
    EOF

Where `<BEAKER_URL>` would be the Beaker service URL, and `<KERBEROS_REALM>`
would be your Kerberos realm. E.g.:

    sudo -u jenkins tee ~jenkins/.beaker_client/config >/dev/null <<"EOF"
    HUB_URL = "https://beaker.example.com"
    AUTH_METHOD = "krbv"
    KRB_REALM = "EXAMPLE.COM"
    EOF

If your Beaker instance is accessed via HTTPS you might need to supply the CA
certificate as well, by adding a line like this to the above configuration:

    CA_CERT = "<CA_CERT>"

Where `<CA_CERT>` would be a path to a CA certificate file in PEM format. E.g.

    sudo -u jenkins tee ~jenkins/.beaker_client/config >/dev/null <<"EOF"
    HUB_URL = "https://beaker.example.com"
    AUTH_METHOD = "krbv"
    KRB_REALM = "EXAMPLE.COM"
    CA_CERT = "/etc/beaker/ca.pem"
    EOF

If you have a keytab for a dedicated principal to use for accessing Beaker,
you can supply it by adding these two lines to the configuration file:

    KRB_KEYTAB = "<KEYTAB>"
    KRB_PRINCIPAL = "<JENKINS_PRINCIPAL>"

Here `<KEYTAB>` would be a path to the keytab file, and `<JENKINS_PRINCIPAL>`
would be the Kerberos principal for Jenkins to use. For example (together with
the CA certificate):

    sudo -u jenkins tee ~jenkins/.beaker_client/config >/dev/null <<"EOF"
    HUB_URL = "https://beaker.example.com"
    AUTH_METHOD = "krbv"
    KRB_REALM = "EXAMPLE.COM"
    CA_CERT = "/etc/beaker/ca.pem"
    KRB_KEYTAB = "/etc/beaker/keytab"
    KRB_PRINCIPAL = "jenkins/special-principals.example.com"
    EOF

Make sure to take steps to protect the keytab file in production environments.

If you don't have a dedicated principal and a keytab, you can omit
`KRB_KEYTAB` and `KRB_PRINCIPAL` settings, and let Jenkins use your Kerberos
credentials like this:

    sudo -u jenkins kinit <YOUR_PRINCIPAL>

Where `<YOUR_PRINCIPAL>` would be the principal you usually login with. E.g.:

    sudo -u jenkins kinit user@EXAMPLE.COM

Note that in this case you will need to periodically refresh the credentials
Jenkins has as they expire, by re-running the command above.

Make sure you get a dedicated principal and a keytab in production
environment, instead of letting Jenkins use your credentials.

### Jenkins

To configure Jenkins, open [http://localhost:8080](http://localhost:8080) in
your browser and follow the wizard. Installing the suggested plugins should be
sufficient. The examples below assume that the admin user, created during
Jenkins configuration, was named "sktm", and assigned password "sesame".

If the Jenkins web-interface fails to open and browser reports connection was
rejected, check if Jenkins is running. On Fedora 28 it fails to start due to
crashing Java interpreter. In that case restart the service with

    sudo systemctl restart jenkins

and try again.

#### Authentication

At the moment, sktm doesn't support CSRF protection when authenticating to
Jenkins. So, after the Jenkins setup is complete, navigate to [Manage Jenkins
-> Configure Global Security](http://localhost:8080/configureSecurity/) and
uncheck the "Prevent Cross Site Request Forgery exploits" checkbox. Note that
you shouldn't do this on production, or exposed systems.

Create a configuration file for Jenkins Job Builder, describing how to access
Jenkins:

    mkdir -p ~/.config/jenkins_jobs
    cat >~/.config/jenkins_jobs/jenkins_jobs.ini <<"EOF"
    [jenkins]
    url=http://localhost:8080
    user=sktm
    password=
    EOF

Then go to ["sktm" user preferences in
Jenkins](http://localhost:8080/user/sktm/configure), click "Show API
token...", copy the text from the displayed "API Token" field, and paste it
into the `password` field value of the configuration file created above. Note:
secure your configuration file appropriately when configuring production
systems.

Test that Jenkins Job Builder can reach and authenticate to Jenkins by running
`jenkins-jobs list`. It should output something like `INFO:root:Matching jobs:
0` and complete succesfully.

#### Serving build artifacts

The Jenkins project description ([example-project.yaml](example-project.yaml))
used in this documentation will run an HTTP server on port 4040 to let Beaker
download the tested kernel images. If your Jenkins host is behind NAT (e.g. in
a VM), make sure to setup port redirection, to have it accessible both
from the Beaker instance and from inside the host, at the same address, and
change the URL skt will be publishing with:

    sed -i -e 's/`hostname -f`:4040/<HOSTNAME>:<PORT>/' example-project.yaml

Here, `<HOSTNAME>` would be the name of the NAT host Beaker would need to
access, and `<PORT>` would be the redirected port number. E.g.:

    sed -i -e 's/`hostname -f`:4040/pc.example.com:4040/' example-project.yaml

You will need to update the file again, if your NAT host name changes.

#### Sending reports

The [`example-project.yaml`](example-project.yaml) file will be instructing
skt to send test results to `Root <root@localhost.localdomain>`. Change the
file if you'd like to send the reports somewhere else:

    sed -i -e 's/Root <root@localhost\.localdomain>/<EMAIL_ADDRESS>/' \
              example-project.yaml

Here, `<EMAIL_ADDRESS>` would be the address to send reports to. E.g.:

    sed -i -e 's/Root <root@localhost\.localdomain>/User <user@example.com>/' \
              example-project.yaml

#### Creating/updating project

Create the Jenkins project for sktm to trigger, from the
[`example-project.yaml`](example-project.yaml) file, using Jenkins Job
Builder:

    jenkins-jobs update example-project.yaml

Then go to the created project in Jenkins UI and click "[Build
Now](http://localhost:8080/job/sktm/build)" to check that it works, and to
have the pipeline parameters (which sktm requires) registered by Jenkins.

Afterwards, every time you would change your YAML project description you will
need to re-run `jenkins-jobs update example-project.yaml` and build the
project manually once, as described above.

### sktm

Create the `~/.sktmrc` file telling sktm how to access Jenkins:

    cat >~/.sktmrc <<"EOF"
    [config]
    jurl = http://localhost:8080
    jlogin = sktm
    jpass = sesame
    EOF

Clone sktm with Git, or simply download and unpack the latest "master" branch
archive. After that, you will be able to run the `sktm.py` executable
directly. The examples below assume you run it while being in the source root
directory, but any directory will do as long as the path to `sktm.py` is
correct.

Usage
-----
On the first execution sktm creates a database file (`~/.sktm.db` by default),
which is then used to track status of tested kernel branches, patches, and
the execution of Jenkins jobs sktm submits.

### Establishing baseline

Before beginning testing a kernel branch, you need to establish a working
"baseline" commit, the patches would be applied on:

    ./sktm.py -v --jjname <JENKINS_PROJECT> baseline <GIT_REPO_URL> <GIT_REF>

Here, `<JENKINS_PROJECT>` would be the name of the Jenkins project running
skt, `<GIT_REPO_URL>` would be a kernel Git repository URL, and `<GIT_REF>`
would be a published Git reference in that repository from which to start
locating a stable "baseline" commit, and usually will be a branch name.

E.g., following our setup example above, this command would find a baseline
commit in the current "scsi" tree:

    ./sktm.py -v --jjname sktm baseline \
              git://git.kernel.org/pub/scm/linux/kernel/git/mkp/scsi.git \
              for-next

And this would do the same for the "net-next" tree:

    ./sktm.py -v --jjname sktm baseline \
              git://git.kernel.org/pub/scm/linux/kernel/git/davem/net-next.git \
              master

You will need to run the "baseline" command periodically to have your baseline
commits up-to-date, to allow newer patches to apply.

### Testing first patches

Once your `baseline` command has finished, you will be able to start checking
patches from a Patchwork instance. However, you would need to specify the
patch to start from on the first run, and would need to use somewhat
different commands for Patchwork v1 and v2 instances.

For Patchwork v1 run:

    ./sktm.py -v --jjname <JENKINS_PROJECT> patchwork \
              <GIT_REPO_URL> \
              <PATCHWORK_BASE_URL> <PATCHWORK_PROJECT> \
              --lastpatch <PATCHWORK_PATCH_ID>

and for Patchwork v2 run:

    ./sktm.py -v --jjname <JENKINS_PROJECT> patchwork \
              <GIT_REPO_URL> \
              --restapi <PATCHWORK_BASE_URL> <PATCHWORK_PROJECT> \
              --lastpatch <PATCHWORK_TIMESTAMP>

Here, `<PATCHWORK_BASE_URL>` would be the base URL of the Patchwork instance,
`<PATCHWORK_PROJECT>` - the name of the Patchwork project to check for new
patches. The `<PATCHWORK_PATCH_ID>` would be the ID of the newest patch (as
seen in Patchwork URLs) to ignore. All patches with greater IDs will be
considered for testing. Finally, `<PATCHWORK_TIMESTAMP>` would be a Patchwork
instance timestamp of the newest patch to ignore, in a format acceptable by
Python's `dateutil.parser` module, e.g. from the `Date:` header of a patch
message. All patches with greater timestamps will be considered for testing.

E.g. this command would test all patches after the one with ID 10363835, from
the "scsi" tree's Patchwork v1 instance, applying them onto the latest
baseline commit from the corresponding Git repo:

    ./sktm.py -v --jjname sktm patchwork \
              git://git.kernel.org/pub/scm/linux/kernel/git/mkp/scsi.git \
              https://patchwork.kernel.org linux-scsi \
              --lastpatch 10363835

And this one would test all patches received by the "next-next" tree's
Patchwork v2 instance after `Thu,  3 May 2018 14:35:00 +0100` timestamp:

    ./sktm.py -v --jjname sktm patchwork \
              git://git.kernel.org/pub/scm/linux/kernel/git/davem/net-next.git \
              --restapi https://patchwork.ozlabs.org netdev \
              --lastpatch 'Thu,  3 May 2018 14:35:00 +0100'

Note: do not run the commands above with the `--lastpatch` option value
intact, as that would likely result in a lot of Jenkins jobs submitted,
because development has moved on since the writing of this guide, and many
more patches have been recorded by these Patchwork instances. Look at the
patches in the instances and pick your own values.

### Testing further patches

After this initial run is complete, the sktm database will have the last
tested patch recorded, and further patches could be tested by executing the
"patchwork" commands above without the `--lastpatch` option.

However, it can be used again to push the last tested patch back, and retest
already-tested patches, or to push it forward to skip testing some patches.

License
-------
sktm is distributed under GPLv2 license.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <http://www.gnu.org/licenses/>.

[travis_badge]: https://travis-ci.org/RH-FMK/sktm.svg?branch=master
[travis_page]: https://travis-ci.org/RH-FMK/sktm
[coveralls_badge]: https://coveralls.io/repos/github/RH-FMK/sktm/badge.svg?branch=master
[coveralls_page]: https://coveralls.io/github/RH-FMK/sktm?branch=master
