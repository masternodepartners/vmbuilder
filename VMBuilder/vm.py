#
#    Uncomplicated VM Builder
#    Copyright (C) 2007-2008 Canonical
#    
#    See AUTHORS for list of contributors
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
#    The VM class
import VMBuilder
import VMBuilder.util      as util
import VMBuilder.log       as log
import VMBuilder.disk      as disk
from   VMBuilder.disk      import Disk
from   VMBuilder.exception import VMBuilderException
from gettext import gettext
_ = gettext
import logging
import os
import optparse
import tempfile
import textwrap

class VM(object):
    def __init__(self):
        self.hypervisor = None
        self.distro = None
        self.disks = []
        self.result_files = []
        self.cleanup_cbs = []
        self.optparser = MyOptParser(epilog="ubuntu-vm-builder is Copyright (C) 2007-2008 Canonical Ltd. and written by Soren Hansen <soren@canonical.com>.", usage='%prog hypervisor distro [options]')
        self.optparser.arg_help = (('hypervisor', self.hypervisor_help), ('distro', self.distro_help))
        self.register_base_settings()

    def cleanup(self):
        logging.info("Cleaning up after ourselves")
        while len(self.cleanup_cbs) > 0:
            self.cleanup_cbs.pop(0)()

    def add_clean_cb(self, cb):
        self.cleanup_cbs.insert(0, cb)

    def add_clean_cmd(self, *argv, **kwargs):
        self.add_clean_cb(lambda : util.run_cmd(*argv, **kwargs))

    def distro_help(self):
        return 'Distro. Valid options: %s' % " ".join(VMBuilder.distros.keys())

    def hypervisor_help(self):
        return 'Hypervisor. Valid options: %s' % " ".join(VMBuilder.hypervisors.keys())

    def register_setting(self, *args, **kwargs):
        return self.optparser.add_option(*args, **kwargs)

    def register_setting_group(self, group):
        return self.optparser.add_option_group(group)

    def setting_group(self, *args, **kwargs):
        return optparse.OptionGroup(self.optparser, *args, **kwargs)

    def register_base_settings(self):
        self.register_setting('-c', dest='altconfig', default='~/.ubuntu-vm-builder', help='Specify a optional configuration file [default: %default]')
        self.register_setting('-d', '--dest', help='Specify the destination directory. [default: <hypervisor>-<distro>]')
        self.register_setting('--debug', action='callback', callback=log.set_verbosity, help='Show debug information')
        self.register_setting('-v', '--verbose', action='callback', callback=log.set_verbosity, help='Show progress information')
        self.register_setting('-q', '--quiet', action='callback', callback=log.set_verbosity, help='Silent operation')
        self.register_setting('-t', '--tmp', default=os.environ.get('TMPDIR', '/tmp'), help='Use TMP as temporary working space for image generation. Defaults to $TMPDIR if it is defined or /tmp otherwise. [default: %default]')
        self.register_setting('-o', '--overwrite', action='store_true', default=False, help='Force overwrite of destination directory if it already exist. [default: %default]')
        self.register_setting('--in-place', action='store_true', default=False, help='Install directly into the filesystem images. This is needed if your \$TMPDIR is nodev and/or nosuid, but will result in slightly larger file system images.')
        self.register_setting('--tmpfs', metavar="OPTS", help='Use a tmpfs as the working directory, specifying its size or "-" to use tmpfs default (suid,dev,size=1G).')
        self.register_setting('-m', '--mem', type='int', default=128, help='Assign MEM megabytes of memory to the guest vm. [default: %default]')

    def add_disk(self, *args, **kwargs):
        disk = Disk(self, *args, **kwargs)
        self.disks.append(disk)
        return disk

    def add_filesystem(self, mntpnt, type=None):
        """Adds a filesystem to the virtual machine"""


    def set_distro(self, arg):
        if arg in VMBuilder.distros.keys():
            self.distro = VMBuilder.distros[arg](self)
            self.set_defaults()
        else:
            raise VMBuilderException("Invalid distro. Valid distros: %s" % " ".join(distros.keys()))

    def set_hypervisor(self, arg):
        if arg in VMBuilder.hypervisors.keys():
            self.hypervisor = VMBuilder.hypervisors[arg](self)
            self.set_defaults()
        else:
            raise VMBuilderException("Invalid hypervisor. Valid hypervisors: %s" % " ".join(hypervisors.keys()))

    def set_defaults(self):
        if self.distro and self.hypervisor:
            self.optparser.set_defaults(destdir='%s-%s' % (self.distro.arg, self.hypervisor.arg))

            (settings, dummy) = self.optparser.parse_args([])
            for (k,v) in settings.__dict__.iteritems():
                setattr(self, k, v)

    def create_directory_structure(self):
        # workdir is the tempdir where we do all the work
        self.workdir = self.create_workdir()
        self.add_clean_cmd('rm', '-rf', self.workdir)

        logging.debug('Temporary directory: %s', self.workdir)

        # rootmnt is where the disk images will be mounted
        self.rootmnt = '%s/target' % self.workdir
        logging.debug('Creating the root mount directory: %s', self.rootmnt)
        os.mkdir(self.rootmnt)

        # tmproot it where we build up the guest filesystem
        self.tmproot = '%s/root' % self.workdir
        logging.debug('Creating temporary root: %s', self.tmproot)
        os.mkdir(self.tmproot)

        # destdir is where the user's files will land when they're done
        logging.debug('Creating destination directory: %s', self.destdir)
        os.mkdir(self.destdir)
        self.add_clean_cmd('rmdir', self.destdir, ignore_fail=True)

        self.result_files.append(self.destdir)

    def create_workdir(self):
        return tempfile.mkdtemp('', 'vmbuilder', self.tmp)

    def mount_partitions(self):
        logging.info('Mounting target filesystem')
        parts = disk.get_ordered_partitions(self.disks)
        for part in parts:
            if part.type != VMBuilder.disk.TYPE_SWAP: 
                logging.debug('Mounting %s', part.mntpnt) 
                part.mntpath = '%s%s' % (self.rootmnt, part.mntpnt)
                if not os.path.exists(part.mntpath):
                    os.makedirs(part.mntpath)
                util.run_cmd('mount', part.mapdev, part.mntpath)
                self.add_clean_cmd('umount', part.mntpath, ignore_fail=True)

    def umount_partitions(self):
        logging.info('Unmounting target filesystem')
        parts = VMBuilder.disk.get_ordered_partitions(self.disks)
        parts.reverse()
        for part in parts:
            if part.type != VMBuilder.disk.TYPE_SWAP: 
                logging.debug('Unmounting %s', part.mntpath) 
                util.run_cmd('umount', part.mntpath)
        for disk in self.disks:
            disk.unmap()

    def install(self):
        if self.in_place:
            self.installdir = self.rootmnt
        else:
            self.installdir = self.tmproot

        logging.info("Installing guest operating system. This might take some time...")
        self.distro.install(self.installdir)

        logging.info("Copying to disk images")
        util.run_cmd('rsync', '-aHA', '%s/' % self.tmproot, self.rootmnt)

        logging.info("Installing bootloader")
        self.distro.install_bootloader()

    def create(self):
        util.checkroot()
        finished = False
        try:
            self.create_directory_structure()

            disk.create_partitions(self)

            self.mount_partitions()

            self.install()

            self.umount_partitions()

            self.hypervisor.convert()

            util.fix_ownership(self.result_files)

            finished = True
        except VMBuilderException,e:
            raise e
        finally:
            if not finished:
                logging.critical("Oh, dear, an exception occurred")
            self.cleanup()

class MyOptParser(optparse.OptionParser):
    def format_arg_help(self, formatter):
        result = []
        for arg in self.arg_help:
            result.append(self.format_arg(formatter, arg))
        return "".join(result)

    def format_arg(self, formatter, arg):
        result = []
        arghelp = arg[1]()
        arg = arg[0]
        width = formatter.help_position - formatter.current_indent - 2
        if len(arg) > width:
            arg = "%*s%s\n" % (self.current_indent, "", arg)
            indent_first = formatter.help_position
        else:                       # start help on same line as opts
            arg = "%*s%-*s  " % (formatter.current_indent, "", width, arg)
            indent_first = 0
        result.append(arg)
        help_lines = textwrap.wrap(arghelp, formatter.help_width)
        result.append("%*s%s\n" % (indent_first, "", help_lines[0]))
        result.extend(["%*s%s\n" % (formatter.help_position, "", line)
                           for line in help_lines[1:]])
        return "".join(result)

    def format_option_help(self, formatter=None):
        if formatter is None:
            formatter = self.formatter
        formatter.store_option_strings(self)
        result = []
        if self.arg_help:
            result.append(formatter.format_heading(_("Arguments")))
            formatter.indent()
            result.append(self.format_arg_help(formatter))
            result.append("\n")
            formatter.dedent()
        result.append(formatter.format_heading(_("Options")))
        formatter.indent()
        if self.option_list:
            result.append(optparse.OptionContainer.format_option_help(self, formatter))
            result.append("\n")
        for group in self.option_groups:
            result.append(group.format_help(formatter))
            result.append("\n")
        formatter.dedent()
        # Drop the last "\n", or the header if no options or option groups:
        return "".join(result[:-1])


