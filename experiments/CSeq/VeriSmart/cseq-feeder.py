#!/usr/bin/env python

""" CSeq C Sequentialization Framework
    command-line front-end
    maintained by Truc Nguyen Lam, Univerisity of Southampton
"""
FRAMEWORK_VERSION = 'CSeq-Feeder-1.3'

"""
Description:
    Feeder for Lazy-CSeq (please look at lazy+ai.chain for more details)

TODO:
    -

Changelog:
    2016.08.14  Initial version
"""
import exceptions
import getopt
import glob
import importlib
import inspect
import os.path
import re
import shutil
import sys
import time
import traceback
from time import gmtime, strftime
from tempfile import NamedTemporaryFile
import pycparser
from pycparser.plyparser import ParseError
import core.config
import core.merger
import core.module
import core.parser
import core.utils


class cseqenv:
    cmdline = None      # full command-line
    opts = None         # command-line option-value pairs, e.g. (--input, 'file.c')
    args = None         #

    params = []         # additional front-end input parameters
    paramIDs = []       # parameters ID only
    paramvalues = {}    # param values indexed by param ID

    debug = False       # verbosity level
    showsymbols = False

    chainfile = None    # file with the sequence of modules to execute

    inputfile = None    # input source file to process
    includepath = None  # #include path (for source merging)
    outputfile = None   # TODO not implemented yet

    modules = []        # modules (each performing a single code trasformation)
    transforms = 0      # no. of modules executed so far

    maps = []
    lastlinenoinlastmodule = 0
    outputtofiles = []    # map from merged sources (= Merger's output) to original source file
    premodules = []
    aftermodules = []
    savecommand = {}
    loadcommand = {}


def parseChainCommand(s):
    ret = {}
    l = s.split()
    for i in l:
        pair = i.split('=')
        if len(pair) != 2:
            print "Load file error (%s):\n" % s
            sys.exit(1)
        ret[pair[0]] = pair[1]

    return ret


def moduleparamusage(p):
    abc = "--%s" % (p.id)
    abc += " <%s>" % p.datatype if p.datatype else ''

    opt = 'optional' if p.optional else ''
    opt += ', ' if p.optional and p.default else ''
    opt += 'default:%s%s%s' % (core.utils.colors.HIGHLIGHT, p.default, core.utils.colors.NO) if p.default else ''
    opt = '(%s)' % opt if len(opt) > 0 else opt

    desc = ('\n    ' + ' ' * 26).join([l for l in p.description.split('\n')])  # multiline description

    return "%-26s %s %s" % (abc, desc, opt)


def usage(cmd, errormsg, showhelp=True, detail=False):
    '''
        long help (-H) provides the list of all input and output parameters
        for each module.

        short help (-h) provides only those input parameters
        that must be provided in the command-line

        (i.e. for each module the ones not generated by any of the previous
        modules in the configuration)
    '''

    if showhelp:
        print ""
        print "  CSeq Lazy |  September 2016"
        print ""
        print "Usage: "
        print ""
        print "   %s -h [-l <config>]" % cmd
        print "   %s -i <input.c> [options]" % cmd
        print ""
        print " configuration options: "
        print "   -l,--load=<file>       configuration to use (default:%s%s%s)" % (core.utils.colors.HIGHLIGHT, core.config.defaultchain, core.utils.colors.NO)
        print "   -L,--list-configs      show available configurations"
        print ""
        print " input options:"
        print "   -i,--input=<file>      input filename"
        print "   -I,--include=<path>    include search path (use : as a separator) (default:%s./%s)" % (core.utils.colors.HIGHLIGHT, core.utils.colors.NO)
        print ""

        # Module-specific params for the given chain (or for the default one)
        print " module options:"

        outputparamssofar = []   # used to check which module input params are front-end input
        inputparamssofar = []

        for m in cseqenv.modules + cseqenv.aftermodules:
            if detail:
                print "  [%s]" % m.getname()
                if len(m.inputparamdefs) == len(m.outputparamdefs) == 0:
                    print ''

            try:
                if detail:
                    if len(m.inputparamdefs) > 0:
                        print "     input:"

                for p in m.inputparamdefs:
                    if (p.id not in [q.id for q in outputparamssofar] and
                            p.id not in [q.id for q in inputparamssofar]):
                        inputparamssofar.append(p)
                        print '   ' + moduleparamusage(p)
                    elif detail:
                        print '  (' + moduleparamusage(p) + ')'

                if detail and len(m.inputparamdefs) > 0:
                    print ''

                if detail:
                    if len(m.outputparamdefs) > 0:
                        print "     output:"

                for p in m.outputparamdefs:
                    outputparamssofar.append(p)
                    if detail:
                        abc = "--%s" % (p.id)
                        print "   %-26s %s" % (abc, p.description)

                if detail and len(m.outputparamdefs) > 0:
                    print ''

            except Exception as e:
                print "Module error '%s':\n%s.\n" % (m.getname(), str(e))
                traceback.print_exc(file=sys.stdout)
                sys.exit(1)

        print ""
        print " other options: "
        print "   -h, --help                 show help"
        print "   -H, --detailedhelp         show detailed configuration-specific help"
        print "   -v  --version              show version number"
        print ""

    if errormsg:
        print errormsg + '\n'
        sys.exit(1)

    sys.exit(0)


def listmodulechains():
    list = ''
    for filename in glob.glob('modules/*.chain'):
        list += filename[len('modules/'):-len('.chain')] + ', '
    if list.endswith(', '):
        list = list[:-2]
    return list


def main():
    '''
    # List all pycparser's AST visit_xyz methods
    # (any of them can be overridden in a module)
    #
    k = core.parser.Parser()
    methods = inspect.getmembers(k, predicate=inspect.ismethod)

    for m in methods:
        if m[0].startswith('visit_'): print m[0]

    sys.exit(1)
    '''
    # pkg_resources.get_distribution("pycparserext").version 2015.1
    # pkg_resources.get_distribution("pycparser").version    2.14

    '''                   '''
    ''' I. Initialisation '''
    '''                   '''
    cseqenv.cmdline = sys.argv
    cseqenv.starttime = time.time()    # save wall time

    # Extract the configuration from the command-line or set it to the default.
    cseqenv.chainname = core.utils.extractparamvalue(cseqenv.cmdline, '-l', '--load', core.config.defaultchain)
    cseqenv.chainfile = 'modules/%s.chain' % core.utils.extractparamvalue(cseqenv.cmdline, '-l', '--load', core.config.defaultchain)

    if not core.utils.fileExists(cseqenv.chainfile):
        usage(cseqenv.cmdline[0], 'error: unable to open configuration file (%s)' % cseqenv.chainfile, showhelp=False)

    temporaryfile = NamedTemporaryFile()
    loadtype = 0   # normal

    # Import all modules in the current configuration.
    for modulename in core.utils.printFile(cseqenv.chainfile).splitlines():
        if not modulename.startswith('#') and len(modulename) >= 1:
            modulename = modulename.strip()
            loadtype = 0

            if modulename.startswith("@save"):
                cseqenv.savecommand = parseChainCommand(modulename.replace("@save", "").strip())
                continue

            if modulename.startswith("@load"):
                cseqenv.loadcommand = parseChainCommand(modulename.replace("@load", "").strip())
                continue

            if modulename.startswith("@pre"):
                modulename = modulename.replace("@pre", "").strip()
                loadtype = 1  # pre

            if modulename.startswith("@after"):
                modulename = modulename.replace("@after", "").strip()
                loadtype = 2  # after

            try:
                mod = importlib.import_module('modules.' + modulename)
                if loadtype == 0:
                    cseqenv.modules.append(getattr(mod, modulename)())
                elif loadtype == 1:
                    cseqenv.premodules.append(getattr(mod, modulename)())
                else:
                    cseqenv.aftermodules.append(getattr(mod, modulename)())
            except ImportError as e:
                print "Unable to import module '%s',\nplease check installation.\n" % modulename
                traceback.print_exc(file=sys.stdout)
                sys.exit(1)
            except AttributeError as e:
                print "Unable to load module '%s',\nplease check that the module filename,\nthe entry in the chain-file, and\nthe top-level classname in the module correctly match.\n" % modulename
                traceback.print_exc(file=sys.stdout)
                sys.exit(1)
            except Exception as e:
                print "Unable to initialise module '%s':\n%s.\n" % (modulename, str(e))
                traceback.print_exc(file=sys.stdout)
                sys.exit(1)

    # Init modules.
    for m in cseqenv.modules:
        try:
            if 'init' in dir(m):
                m.init()
        except Exception as e:
            print "Unable to initialise module '%s':\n%s.\n" % (m.getname(), str(e))
            traceback.print_exc(file=sys.stdout)
            sys.exit(1)

    # Init pre modules.
    for m in cseqenv.premodules:
        try:
            if 'init' in dir(m):
                m.init()
        except Exception as e:
            print "Unable to initialise module '%s':\n%s.\n" % (m.getname(), str(e))
            traceback.print_exc(file=sys.stdout)
            sys.exit(1)

    # Init after modules.
    for m in cseqenv.aftermodules:
        try:
            if 'init' in dir(m):
                m.init()
        except Exception as e:
            print "Unable to initialise module '%s':\n%s.\n" % (m.getname(), str(e))
            traceback.print_exc(file=sys.stdout)
            sys.exit(1)

    # Init module parameters.
    #
    # Modules can have input and output parameters.
    # Any module input that is not the output of a previous module
    # is a front-end parameter
    # (it is displayed in the usage() screen, and
    #  it can be provided to the front-end in the command-line)
    inParams = []      # module-specific input parameters seen so far
    inParamIDs = []
    inparamvalues = {}

    outParams = []     # module-specific output parameters seen so far
    outParamIDs = []
    outparamvalues = {}

    for m in cseqenv.modules + cseqenv.aftermodules:
        try:
            for p in m.inputparamdefs:  # global input params seen so far
                if p.id not in inParamIDs:
                    inParamIDs.append(p.id)
                    inParams.append(p)

                # if the input param  p  is new and
                # no previous module generates it
                # (i.e., it is not an output param for any previous module)
                # then it needs to be a global (front-end) input
                if p.id not in outParamIDs:
                    cseqenv.paramIDs.append(p.id)
                    cseqenv.params.append(p)

            for p in m.outputparamdefs:  # output params seen so far
                if p.id not in outParamIDs:
                    outParamIDs.append(p.id)
                    outParams.append(p)
        except Exception as e:
            print "Unable to initialise module '%s':\n%s.\n" % (m.getname(), str(e))
            traceback.print_exc(file=sys.stdout)
            sys.exit(1)

    '''                '''
    ''' II. Parameters '''
    '''                '''
    # Parse command-line.
    try:
        shortargs = "hHdi:o:I:e:DSMvl:L"
        longargs = ["help", "detailedhelp", "detail", "input=", "output=", "include=",
                    "error-label=",
                    "debug", "symbols", "modules", "version",
                    "load=", "list-configs"]    # <-- append module params here

        # add one command-line parameter for each module-specific parameter
        for p in cseqenv.params:
            longargs.append("%s%s" % (p.id, '' if p.isflag() else '='))

        cseqenv.opts, cseqenv.args = getopt.getopt(sys.argv[1:], shortargs, longargs)
    except getopt.GetoptError, err:
        usage(cseqenv.cmdline[0], 'error: ' + str(err))

    for o, a in cseqenv.opts:
        if o in ("-v", "--version"):
            print FRAMEWORK_VERSION
            return
        elif o in ("-h", "--help"):
            usage(cseqenv.cmdline[0], '')
        elif o in ("-H", "--detailedhelp"):
            usage(cseqenv.cmdline[0], '', detail=True)
        elif o in ("-l", "--load"):
            pass  # handled beforehand, see above
        elif o in ("-L", "--list-configs"):
            print listmodulechains()
            sys.exit(0)
        elif o in ("-D", "--debug"):
            cseqenv.debug = True
        elif o in ("-S", "--showsymbols"):
            cseqenv.showsymbols = True
        elif o in ("-d", "--detail"):
            detail = True
        elif o in ("-i", "--input"):
            cseqenv.inputfile = a
        elif o in ("-o", "--output"):
            cseqenv.outputfile = a
        elif o in ("-I", "--include"):
            cseqenv.includepath = a
        else:  # module-specific parameters
            cseqenv.paramvalues[o[2:]] = a

    # Basic parameter check.
    if not cseqenv.inputfile:
        usage(cseqenv.cmdline[0], 'error: input file name not specified.')
    if not core.utils.fileExists(cseqenv.inputfile):
        usage(cseqenv.cmdline[0], 'error: unable to open input file (%s)' % cseqenv.inputfile, showhelp=False)
    if not core.utils.fileExists(cseqenv.chainfile):
        usage(cseqenv.cmdline[0], 'error: unable to open module-chain file (%s)' % cseqenv.chainfile, showhelp=False)

    # All global parameters (calculated above) should be in the command-line.
    for p in cseqenv.params:
        if not p.optional and not p.default:
            usage(cseqenv.cmdline[0], 'error: %s (option --%s) not specified.' % (p.description, p.id))

    # Debug setup.
    cseqenv.debugpath = core.config.debugpath
    if not os.path.exists(core.config.debugpath):
        os.makedirs(core.config.debugpath)
    elif cseqenv.debug:
        shutil.rmtree(core.config.debugpath)
        os.makedirs(core.config.debugpath)

    '''              '''
    ''' III. Merging '''
    '''              '''
    # Load the input file.
    input = core.utils.printFileRows(cseqenv.inputfile)

    # Patch for SVCOMP2016 .i file
    if cseqenv.inputfile.endswith(".i") and core.utils.isPreprocessed(cseqenv.inputfile):
        input = core.utils.stripIfNeeded(cseqenv.inputfile)[1]
        cseqenv.inputfile = cseqenv.inputfile[:-2] + '.c'
        core.utils.saveFile(cseqenv.inputfile, input)

    # Merge all the source files into a single string.
    try:
        cseqenv.moduleID = 'merger'

        Merger = core.merger.Merger()
        Merger.loadfromstring(input, cseqenv)
        output = Merger.getoutput()
        cseqenv.transforms += 1

        if cseqenv.debug:
            core.utils.saveFile('%s/_000_input___merger.c' % core.config.debugpath, input)
            core.utils.saveFile('%s/_000_marked__merger.c' % cseqenv.debugpath, Merger.markedoutput)
            core.utils.saveFile('%s/_000_output__merger.c' % core.config.debugpath, output)
            core.utils.saveFile('%s/_000_linemap__merger.c' % core.config.debugpath, Merger.getlinenumbertable())

    except ParseError as e:
        print "Parse error (%s):\n" % str(e)
        print "%s%s%s" % (core.utils.colors.HIGHLIGHT, core.utils.snippet(output, Merger.getLineNo(e), Merger.getColumnNo(e), 5, True), core.utils.colors.NO)
        sys.exit(1)
    except exceptions.SystemExit as e:  # the module invoked sys.exit()
        sys.exit(1)
    except:
        traceback.print_exc(file=sys.stdout)
        sys.exit(1)

    #
    if cseqenv.showsymbols:
        Parser = core.parser.Parser()
        Parser.loadfromstring(output)
        Parser.ast.show()
        sys.exit(0)

    '''                    '''
    ''' IV. Transformation '''
    '''                    '''
    cseqenv.maps.append(Merger.outputtoinput)
    cseqenv.outputtofiles = Merger.outputtofiles

    # Run all modules in a sequence
    for cseqenv.transforms, m in enumerate(cseqenv.modules):
        try:
            timeBefore = time.time()
            if cseqenv.debug:
                print "/* " + m.getname(),

            m.initParams(cseqenv)
            m.loadfromstring(output, cseqenv)
            output = m.getoutput()

            if 'inputtooutput' in dir(m):   # linemapping only works on Translator (C-to-C) modules
                cseqenv.maps.append(m.outputtoinput)
                cseqenv.lastlinenoinlastmodule = m.output.count('\n')

            if cseqenv.debug:
                fileno = '0' + str(cseqenv.transforms + 1).zfill(2)
                core.utils.saveFile('%s/_%s_input___%s.c' % (cseqenv.debugpath, fileno, m.getname()), m.input)
                core.utils.saveFile('%s/_%s_output__%s.c' % (cseqenv.debugpath, fileno, m.getname()), m.output)
                try:
                    # core.utils.saveFile('%s/_%s_ast__%s.c' % (cseqenv.debugpath,fileno,m.getname()), str(m.Parser.ast.show()))
                    core.utils.saveFile('%s/_%s_symbols__%s.c' % (cseqenv.debugpath, fileno, m.getname()), m.Parser.printsymbols())
                except AttributeError:
                    pass
                print "[%s] ok %0.2fs */" % (fileno, int(time.time()) - int(timeBefore))

            if cseqenv.debug and 'markedoutput' in dir(m):  # current module is a Translator
                core.utils.saveFile('%s/_%s_marked__%s.c' % (cseqenv.debugpath, fileno, m.getname()), m.markedoutput)
                core.utils.saveFile('%s/_%s_linemap__%s.c' % (cseqenv.debugpath, fileno, m.getname()), m.getlinenumbertable())

        except ParseError as e:
            print "Parse error (%s) while performing %s->%s:\n" % (str(e), cseqenv.modules[cseqenv.transforms - 1].getname() if cseqenv.transforms > 0 else '', cseqenv.modules[cseqenv.transforms].getname())
            print "%s%s%s" % (core.utils.colors.HIGHLIGHT, core.utils.snippet(output, m.getLineNo(e), m.getColumnNo(e), 5, True), core.utils.colors.NO)
            sys.exit(1)
        except core.module.ModuleParamError as e:
            print "Module error (%s).\n" % (str(e))
            sys.exit(1)
        except core.module.ModuleError as e:
            print "Error from %s module: %s.\n" % (cseqenv.modules[cseqenv.transforms].getname(), str(e)[1:-1])
            sys.exit(1)
        except KeyboardInterrupt as e:
            sys.exit(1)
        except ImportError as e:
            print "Import error (%s),\nplease re-install the tool.\n" % str(e)
            traceback.print_exc(file=sys.stdout)
            sys.exit(1)
        except Exception as e:
            print "Error while performing %s->%s:\n" % (cseqenv.modules[cseqenv.transforms - 1].getname() if cseqenv.transforms > 0 else '', cseqenv.modules[cseqenv.transforms].getname())
            traceback.print_exc(file=sys.stdout)
            sys.exit(1)

    cachedOutput = output
    # For the sack of preanalysis
    temporaryfile = NamedTemporaryFile()

    # save environment if there is save and log
    cachedparams = {}
    for item in cseqenv.savecommand:
        if item == 'backend' and item not in cseqenv.paramvalues:
            cseqenv.paramvalues[item] = 'cbmc'
        if item == 'rounds' and item in cseqenv.paramvalues and int(cseqenv.paramvalues[item]) > 1:
            cseqenv.savecommand[item] = cseqenv.paramvalues[item]
        if item in cseqenv.paramvalues:
            cachedparams[item] = cseqenv.paramvalues[item]

    # Set environment for pre-module if applicable
    for item in cseqenv.savecommand:
        if cseqenv.savecommand[item] == 'tempfile':
            cseqenv.paramvalues[item] = temporaryfile.name
        else:
            cseqenv.paramvalues[item] = cseqenv.savecommand[item]

    # Pre-modules
    timepremodules = time.time()
    output = cachedOutput

    for cseqenv.transforms, m in enumerate(cseqenv.premodules):
        try:
            timeBefore = time.time()
            if cseqenv.debug:
                print "/* " + m.getname(),

            m.initParams(cseqenv)
            m.loadfromstring(output, cseqenv)
            output = m.getoutput()

            if cseqenv.debug:
                fileno = '1' + str(cseqenv.transforms + 1).zfill(2)
                core.utils.saveFile('%s/_%s_input___%s.c' % (cseqenv.debugpath, fileno, m.getname()), m.input)
                core.utils.saveFile('%s/_%s_output__%s.c' % (cseqenv.debugpath, fileno, m.getname()), m.output)
                try:
                    # core.utils.saveFile('%s/_%s_ast__%s.c' % (cseqenv.debugpath,fileno,m.getname()), str(m.Parser.ast.show()))
                    core.utils.saveFile('%s/_%s_symbols__%s.c' % (cseqenv.debugpath, fileno, m.getname()), m.Parser.printsymbols())
                except AttributeError:
                    pass
                print "[%s] ok %0.2fs */" % (fileno, int(time.time()) - int(timeBefore))

            if cseqenv.debug and 'markedoutput' in dir(m):  # current module is a Translator
                core.utils.saveFile('%s/_%s_marked__%s.c' % (cseqenv.debugpath, fileno, m.getname()), m.markedoutput)
                core.utils.saveFile('%s/_%s_linemap__%s.c' % (cseqenv.debugpath, fileno, m.getname()), m.getlinenumbertable())

        except ParseError as e:
            print "Parse error (%s) while performing %s->%s:\n" % (str(e), cseqenv.premodules[cseqenv.transforms - 1].getname() if cseqenv.transforms > 0 else '', cseqenv.premodules[cseqenv.transforms].getname())
            print "%s%s%s" % (core.utils.colors.HIGHLIGHT, core.utils.snippet(output, m.getLineNo(e), m.getColumnNo(e), 5, True), core.utils.colors.NO)
            sys.exit(1)
        except core.module.ModuleParamError as e:
            print "Module error (%s).\n" % (str(e))
            sys.exit(1)
        except core.module.ModuleError as e:
            print "Error from %s module: %s.\n" % (cseqenv.premodules[cseqenv.transforms].getname(), str(e)[1:-1])
            sys.exit(1)
        except KeyboardInterrupt as e:
            sys.exit(1)
        except ImportError as e:
            print "Import error (%s),\nplease re-install the tool.\n" % str(e)
            traceback.print_exc(file=sys.stdout)
            sys.exit(1)
        except Exception as e:
            print "Error while performing %s->%s:\n" % (cseqenv.premodules[cseqenv.transforms - 1].getname() if cseqenv.transforms > 0 else '', cseqenv.premodules[cseqenv.transforms].getname())
            traceback.print_exc(file=sys.stdout)
            sys.exit(1)

    # After-modules
    # remove added parameter
    for item in cseqenv.savecommand:
        if item in cseqenv.paramvalues:
            del cseqenv.paramvalues[item]

    # restore cached parameter
    for item in cachedparams:
        cseqenv.paramvalues[item] = cachedparams[item]

    # load new parameter
    for item in cseqenv.loadcommand:
        if item.startswith('env.'):   # which mean the environment gonna be set
            attri = item.replace('env.', '')
            if cseqenv.loadcommand[item] == '<get_time>':
                setattr(cseqenv, attri, time.time() - timepremodules)
            else:
                setattr(cseqenv, attri, cseqenv.loadcommand[item])
        else:
            if cseqenv.loadcommand[item] == 'tempfile':
                cseqenv.paramvalues[item] = temporaryfile.name

    output = cachedOutput

    for cseqenv.transforms, m in enumerate(cseqenv.aftermodules):
        try:
            timeBefore = time.time()
            if cseqenv.debug:
                print "/* " + m.getname(),

            m.initParams(cseqenv)
            m.loadfromstring(output, cseqenv)
            output = m.getoutput()

            if 'inputtooutput' in dir(m):   # linemapping only works on Translator (C-to-C) modules
                cseqenv.maps.append(m.outputtoinput)
                cseqenv.lastlinenoinlastmodule = m.output.count('\n')

            if cseqenv.debug:
                fileno = '2' + str(cseqenv.transforms + 1).zfill(2)
                core.utils.saveFile('%s/_%s_input___%s.c' % (cseqenv.debugpath, fileno, m.getname()), m.input)
                core.utils.saveFile('%s/_%s_output__%s.c' % (cseqenv.debugpath, fileno, m.getname()), m.output)
                try:
                    # core.utils.saveFile('%s/_%s_ast__%s.c' % (cseqenv.debugpath,fileno,m.getname()), str(m.Parser.ast.show()))
                    core.utils.saveFile('%s/_%s_symbols__%s.c' % (cseqenv.debugpath, fileno, m.getname()), m.Parser.printsymbols())
                except AttributeError:
                    pass
                print "[%s] ok %0.2fs */" % (fileno, int(time.time()) - int(timeBefore))

            if cseqenv.debug and 'markedoutput' in dir(m):  # current module is a Translator
                core.utils.saveFile('%s/_%s_marked__%s.c' % (cseqenv.debugpath, fileno, m.getname()), m.markedoutput)
                core.utils.saveFile('%s/_%s_linemap__%s.c' % (cseqenv.debugpath, fileno, m.getname()), m.getlinenumbertable())

        except ParseError as e:
            print "Parse error (%s) while performing %s->%s:\n" % (str(e), cseqenv.aftermodules[cseqenv.transforms - 1].getname() if cseqenv.transforms > 0 else '', cseqenv.aftermodules[cseqenv.transforms].getname())
            print "%s%s%s" % (core.utils.colors.HIGHLIGHT, core.utils.snippet(output, m.getLineNo(e), m.getColumnNo(e), 5, True), core.utils.colors.NO)
            sys.exit(1)
        except core.module.ModuleParamError as e:
            print "Module error (%s).\n" % (str(e))
            sys.exit(1)
        except core.module.ModuleError as e:
            print "Error from %s module: %s.\n" % (cseqenv.aftermodules[cseqenv.transforms].getname(), str(e)[1:-1])
            sys.exit(1)
        except KeyboardInterrupt as e:
            sys.exit(1)
        except ImportError as e:
            print "Import error (%s),\nplease re-install the tool.\n" % str(e)
            traceback.print_exc(file=sys.stdout)
            sys.exit(1)
        except Exception as e:
            print "Error while performing %s->%s:\n" % (cseqenv.aftermodules[cseqenv.transforms - 1].getname() if cseqenv.transforms > 0 else '', cseqenv.aftermodules[cseqenv.transforms].getname())
            traceback.print_exc(file=sys.stdout)
            sys.exit(1)

    temporaryfile.close()
    print output
    return


if __name__ == "__main__":
    main()
