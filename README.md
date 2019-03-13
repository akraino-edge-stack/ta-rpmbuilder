# RPMBuilder

This tool allows you to build RPM files in mock environment.

## What is Mock?

Mock is a tool for building packages. It can build packages for different architectures and
different Fedora or RHEL versions than the build host has. Mock creates chroots and builds packages
in them. Its only task is to reliably populate a chroot and attempt to build a package in that
chroot.

Source: https://fedoraproject.org/wiki/Mock?rd=Subprojects/Mock


## How does rpmbuilder work?

Tool reads user provided configuration and creates checkouts of Mock settings and Git hosted
projects. Dependency mapping between projects is created from spec files found in every project.
When a project is build the spec file is patched so that "Version:" field is set to "git describe"
value. The "Release:" field is incremented based on existing rpm files.

The idea for this tool has been taken from openSuse Build Service (OBS). Own tool was created since
configuring OBS takes a lot of work and it does not have great support for password protected Git
repositories.


## Prerequisite

### Installing mock and createrepo

As a requirement for the tool to work, you need to install rpm building tool "mock" and repository
tool "createrepo" to your host.

In Redhat/Fedora:
```
$ yum install mock createrepo rpmdevtools
```

Ubuntu:
```
$ apt-get install mock createrepo
```

### Assign users to mock group

Users of mock also need to belong to group "mock". This allows them to run mock which uses chroot.

Create mock group if it does not exists in your host
```
$ getent group mock || groupadd mock
```

Add yourself to mock group
```
$ usermod -a -G mock <username>
```


## Running script

Create a workspace directory which builder can use to do checkouts and compilation. This directory
should have sufficient space to store your checkouts and rpm files.

Example:
```
$ mkdir /home/<username>/rpmworkspace
```

### Building project to a rpm file

You can build local projects as rpm files. This is useful if you are developing a project and want
to create rpm files without commiting to version control system.

Example of building helloworld to rpm:
```
$ ./makebuild.py -w /home/<username>/rpmworkspace /home/<username>/helloworld
```

If you want to reconfigure Mock environment (e.g. extra Yum repositories) to be available during
building, create a copy of default Mock configuration and provide it with -m option.

Example:
```
$ cp defaults/epel-7-x86_64.cfg ~/mymock.cfg
$ vim ~/mymock.cfg
$ ./makebuild.py -w /home/<username>/rpmworkspace -m ~/mymock.cfg /home/<username>/helloworld
```

Note:
 - RPM package version is created from "git describe". If git describe cannot be used, package
   version is hard coded to a.b

### Access built RPM packages

If there are no errors during building, rpm files can be copied from build repository under your
workspace directory.
Example: /home/<username>/rpmworkspace/buildrepository/epel-7-x86_64/


## RPM file name convention

Rpm packages are named and versioned so that it can be found from version control system. Rpmbuilder
uses command "git describe --dirty --tags" to produce a rpm package file name. If git is unable to
describe the checkout a another "git describe --dirty --all --always" command is used.

**Example 1:** Clone with no tags
File name mymodule-master.c110.gce32b26-1.el7.x86_64.rpm states that package mymodule has been made
from master branch. Package was made from 110th commit and this commit has git hash ce32b26.

**Example 2:** Clone with tag 1.0
File name mymodule-1.0-1.el7.x86_64.rpm shows that mymodule package was made from tag 1.0.

**Example 3:** Clone with two changes on top of tag 1.0 git clone
File mymodule-1.0.c2.gad96bc2-1.el7.x86_64.rpm shows two changes have been made on top of 1.0 and
also the identifying hash.

**Example 4:** Clone from Example 3 and local changes
File mymodule-master.dirty.c112.g1.0.2.g8193b3a-1.el7.x86_64.rpm shows that the clone directory
contains local modifications which make it dirty.


## More usage examples

### Storing build products to remote server

If projects are built in Jenkins, there is always danger that somebody might wipe the workspace. To
protect against workspace wiping you can use stashmakebuild.py script. In your build configuration
file define remote server and directory.

When building starts script checks from your workspace that you have directories for projects and
builder. If these are missing, your remote server/directory is used to pull previous build state.
After each successful build your project configuration and rpm files are stored to remote server.

With safemakebuild.py you need to use two additional properties: --remotehost and --remotedir.

### Create package with version taken from Git

To read package verion from Git ("git describe") set the package Version directive in spec file as
"%{_version}".

### Build multiple Git projects with a build configuration file

Create a configuration file which contains information about the projects and mock environment.
Syntax for the configuration file can be copied from provided configuration-example.ini file.

Example:
```
$ cp configuration-example.ini /home/<username>/buildconfig.ini
$ vim /home/<username>/buildconfig.ini
$ ./makebuild.py -w /home/<username>/rpmworkspace -b /home/<username>/buildconfig.ini
```

Note:
 - Builder keeps track of Git commit hash. Rpm building if done if project hash has changed.
 - If commit hash has not changed since previous build, building is skipped.


## Known issues

1. If you are not using RedHat, CentOS or Fedora building hosts you might have problems running
   mock. Build requirements that have been installed by rpmbuilder to mock chroot, might not be
recognized by rpm tools during building. Because of this rpm building will fail complaining that
necessary build requirements are missing.

If your components do not have build requirements to each other, then there are no problems. This
problem has been seen with Debian based distributions and it is a known bug:
https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=794495

Also spectool seems to be missing from Debian based packages. Without this tool rpmbuilder is
cripled to work only with local source files. As long as you do not have any spec lines such as
"SourceX http://example.com/package.tgz" you are safe.
See **Debian custom spectool intallation** chapter how to install spectool to your home directory.


2. If you change git repository url this will force rebuilding of this project even if the hash of
   the code remains unchanged.

### Debian custom spectool intallation

Clone spectool git somewhere in your home directory. For example to ~/gitrepos -directory:
```
cd gitrepos
git clone https://pagure.io/spectool.git
```
Create a symbolic link to spectool where your search PATH can find it.
```
ln -s ~/gitrepos/spectool/spectool ~/bin/
```
