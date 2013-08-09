"""clangparser - use clang to get preprocess a source code."""

import clang.cindex 
from clang.cindex import Index
from clang.cindex import CursorKind, TypeKind
import ctypes

import logging

import codegenerator
import typedesc
import sys
import re

from . import util

log = logging.getLogger('clangparser')

def decorator(dec):
    def new_decorator(f):
        g = dec(f)
        g.__name__ = f.__name__
        g.__doc__ = f.__doc__
        g.__dict__.update(f.__dict__)
        return g
    new_decorator.__name__ = dec.__name__
    new_decorator.__doc__ = dec.__doc__
    new_decorator.__dict__.update(dec.__dict__)
    return new_decorator

@decorator
def log_entity(func):
    def fn(*args, **kwargs):
        log.debug("%s: spelling:'%s'"%(func.__name__, args[1].spelling))
        #print 'calling {}'.format(func.__name__)
        return func(*args, **kwargs)
    return fn

################################################################

def MAKE_NAME(name):
    for k, v in [('<','_'), ('>','_'), ('::','__'), (',',''), (' ',''),
                 ("$", "DOLLAR"), (".", "DOT"), ("@", "_"), (":", "_")]:
        if k in name: # template
            name = name.replace(k,v)
    if name.startswith("__"):
        return "_X" + name
    elif name[0] in "01234567879":
        return "_" + name
    return name

WORDPAT = re.compile("^[a-zA-Z_][a-zA-Z0-9_]*$")

def CHECK_NAME(name):
    if WORDPAT.match(name):
        return name
    return None

''' 
clang2py test1.cpp -triple "x86_64-pc-linux-gnu" 
clang2py test1.cpp -triple i386-pc-linux-gnu

'''
class Clang_Parser(object):
    # clang.cindex.CursorKind
    ## Declarations: 1-39
    ## Reference: 40-49
    ## Invalids: 70-73
    ## Expressions: 100-143
    ## Statements: 200-231
    ## Root Translation unit: 300
    ## Attributes: 400-403
    ## Preprocessing: 500-503
    has_values = set(["Enumeration", "Function", "FunctionType",
                      "OperatorFunction", "Method", "Constructor",
                      "Destructor", "OperatorMethod",
                      "Converter"])

    ctypes_typename = {
        TypeKind.VOID : 'void' ,
        TypeKind.BOOL : 'c_bool' ,
        TypeKind.CHAR_U : 'c_ubyte' ,
        TypeKind.UCHAR : 'c_ubyte' ,
        TypeKind.CHAR16 : 'c_wchar' ,
        TypeKind.CHAR32 : 'c_wchar*2' ,
        TypeKind.USHORT : 'TBD' ,
        TypeKind.UINT : 'TBD' ,
        TypeKind.ULONG : 'TBD' ,
        TypeKind.ULONGLONG : 'TBD' ,
        TypeKind.UINT128 : 'c_uint128' ,
        TypeKind.CHAR_S : 'c_byte' ,
        TypeKind.SCHAR : 'c_byte' ,
        TypeKind.WCHAR : 'c_wchar' ,
        TypeKind.SHORT : 'TBD' ,
        TypeKind.INT : 'TBD' ,
        TypeKind.LONG : 'TBD' ,
        TypeKind.LONGLONG : 'TBD' ,
        TypeKind.INT128 : 'c_int128' ,
        TypeKind.FLOAT : 'c_float' , # FIXME
        TypeKind.DOUBLE : 'c_double' , # FIXME
        TypeKind.LONGDOUBLE : 'TBD' ,
    }
    records={}
    fields={}
    def __init__(self, *args):
        #self.args = *args
        self.all = {}
        self.records = {}
        self.fields = {}
        self.cpp_data = {}
        self._unhandled = []
        self.tu = None
        self.make_ctypes_convertor()

    def parse(self, args):
        index = Index.create()
        self.tu = index.parse(None, args)
        if not self.tu:
            log.warning("unable to load input")
            return
        if len(self.tu.diagnostics)>0:
            for x in self.tu.diagnostics:
                if x.severity > 2:
                    log.warning("Source code has some error. Please fix.")
                    break
        root = self.tu.cursor
        for node in root.get_children():
            self.startElement( node )


    def startElement(self, node ): #kind, attrs):
        if node is None:
            return

        # find and call the handler for this element
        mth = getattr(self, node.kind.name)
        if mth is None:
            return
        
        log.debug('Found a %s|%s|%s'%(node.kind.name, node.displayname, node.spelling))
        
        result = mth(node)
        if result is None:
            return
        #if isinstance(result, (str,)):
        #    return

        if node.location.file is not None:
            #print result, node
            result.location = node.location

        ## self.all[_id] should return the Typedesc object, so that type(x).__name__ is a local func to codegen object
        _id = node.get_usr()
        #print '++ startElement _id ', _id
        if _id != '' and result is not None: # TYPE_REF, Ignore.        
            self.all[_id] = result
        
        # if this element has children, treat them.
        # if name in self.has_values:

        for child in node.get_children():
            self.startElement( child )          
        return result

    def register(self, name, obj):
        if name in self.all:
            log.debug('register: %s already existed %s|%s'%(name,self.all[name],obj))
        self.all[name]=obj
        return obj

    def is_registered(self, name):
        if name not in self.all:
            return None
        return self.all[name]

    ########################################################################
    # clang types to ctypes
    def make_ctypes_convertor(self):
        tu = util.get_tu('''
typedef short short_t;
typedef int int_t;
typedef long long_t;
typedef long long longlong_t;
typedef float float_t;
typedef double double_t;
typedef long double longdouble_t;''')
        size = util.get_cursor(tu, 'short_t').type.get_size()*8
        self.ctypes_typename[TypeKind.SHORT] = 'c_int%d'%(size)
        self.ctypes_typename[TypeKind.USHORT] = 'c_uint%d'%(size)

        size = util.get_cursor(tu, 'int_t').type.get_size()*8
        self.ctypes_typename[TypeKind.INT] = 'c_int%d'%(size)
        self.ctypes_typename[TypeKind.UINT] = 'c_uint%d'%(size)

        size = util.get_cursor(tu, 'long_t').type.get_size()*8
        self.ctypes_typename[TypeKind.LONG] = 'c_int%d'%(size)
        self.ctypes_typename[TypeKind.ULONG] = 'c_uint%d'%(size)

        size = util.get_cursor(tu, 'longlong_t').type.get_size()*8
        self.ctypes_typename[TypeKind.LONGLONG] = 'c_int%d'%(size)
        self.ctypes_typename[TypeKind.ULONGLONG] = 'c_uint%d'%(size)
        
        #FIXME : Float && http://en.wikipedia.org/wiki/Long_double
        size0 = util.get_cursor(tu, 'float_t').type.get_size()*8
        size1 = util.get_cursor(tu, 'double_t').type.get_size()*8
        size2 = util.get_cursor(tu, 'longdouble_t').type.get_size()*8
        if size1 != size2:
            self.ctypes_typename[TypeKind.LONGDOUBLE] = 'c_double%d'%(size2)
        else:
            self.ctypes_typename[TypeKind.LONGDOUBLE] = 'c_double'

        log.debug('ARCH sizes: long:%s longdouble:%s'%(
                self.ctypes_typename[TypeKind.LONG],
                self.ctypes_typename[TypeKind.LONGDOUBLE]))
    
    def is_fundamental_type(self, t):
        return t.kind in self.ctypes_typename.keys()

    def convert_to_ctypes(self, typ):
        return self.ctypes_typename[typ]
        

    ################################
    # do-nothing element handlers

    #def Class(self, attrs): pass
    def Destructor(self, attrs): pass
    
    cvs_revision = None
    def GCC_XML(self, attrs):
        rev = attrs["cvs_revision"]
        self.cvs_revision = tuple(map(int, rev.split(".")))

    def Namespace(self, attrs): pass

    def Base(self, attrs): pass
    def Ellipsis(self, attrs): pass
    def OperatorMethod(self, attrs): pass


    ###########################################
    # ATTRIBUTES
    
    @log_entity
    def UNEXPOSED_ATTR(self, cursor): 
        parent = cursor.semantic_parent
        #print 'parent is',parent.displayname, parent.location, parent.extent
        # TODO until attr is exposed by clang:
        # readlines()[extent] .split(' ') | grep {inline,packed}
        pass

    @log_entity
    def PACKED_ATTR(self, cursor): 
        parent = cursor.semantic_parent
        #print 'parent is',parent.displayname, parent.location, parent.extent
        # TODO until attr is exposed by clang:
        # readlines()[extent] .split(' ') | grep {inline,packed}
        pass

    ################################
    # real element handlers

    #def CPP_DUMP(self, attrs):
    #    name = attrs["name"]
    #    # Insert a new list for each named section into self.cpp_data,
    #    # and point self.cdata to it.  self.cdata will be set to None
    #    # again at the end of each section.
    #    self.cpp_data[name] = self.cdata = []

    #def characters(self, content):
    #    if self.cdata is not None:
    #        self.cdata.append(content)

    #def File(self, attrs):
    #    name = attrs["name"]
    #    if sys.platform == "win32" and " " in name:
    #        # On windows, convert to short filename if it contains blanks
    #        from ctypes import windll, create_unicode_buffer, sizeof, WinError
    #        buf = create_unicode_buffer(512)
    #        if windll.kernel32.GetShortPathNameW(name, buf, sizeof(buf)):
    #            name = buf.value
    #    return typedesc.File(name)
    #
    #def _fixup_File(self, f): pass
    
    def get_token(self, cursor):
        init = None
        for c in cursor.get_children():
            print c.displayname
            for t in c.get_tokens():
                init = t.spelling
                print init
                break
            break
            #print init
        #print 'VAR_DECL init', init
        try:
            int(init)
        except:
            init = None
        return init
    
    # simple types and modifiers
    # FIXME, token is bad, ar_ref is bad
    @log_entity
    def VAR_DECL(self, cursor):
        import code
        #code.interact(local=locals())
        
        name = cursor.displayname
        if name.startswith("cpp_sym_"):
            # XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXx fix me!
            name = name[len("cpp_sym_"):]
        # I dont have the value... 
        init = None
        for c in cursor.get_children():
            for t in c.get_tokens():
                init = t.spelling
                break
            break
            #print init
        
            log.debug('VAR_DECL init:%s'%(init))
        
        try:
            int(init)
        except:
            init = None
        # now get the type
        typ = cursor.type.get_canonical()
        # FIXME - feels weird
        if self.is_fundamental_type(typ):
            ctypesname = self.convert_to_ctypes(typ)
            typ = typedesc.FundamentalType( ctypesname, 0, 0 )
        else:
            typ = cursor.get_usr() #cursor.type.get_canonical().kind.name

        #print typ.__class__.__name__
        return typedesc.Variable(name, typ, init)

    def _fixup_Variable(self, t):
        if type(t.typ) == str: #typedesc.FundamentalType:
            t.typ = self.all[t.typ]

    #def Typedef(self, attrs):
    @log_entity
    def TYPEDEF_DECL(self, cursor):
        name = cursor.displayname
        log.debug("TYPEDEF_DECL: name:%s"%(name))
        typ = cursor.type.get_canonical()
        log.debug("TYPEDEF_DECL: typ:%s"%(typ.kind.spelling))
        # FIXME feels weird not to call self.fundamental
        if self.is_fundamental_type(typ):
            ctypesname = self.convert_to_ctypes(typ.kind)
            typ = typedesc.FundamentalType( ctypesname, 0, 0 )
            log.debug("TYPEDEF_DECL: fundamental typ:%s"%(typ))
        else: # make typ or get it from self.all
            _id = cursor.get_definition().type.get_declaration().get_usr()
            if _id in self.all:
                typ = self.all[_id]
            else:
                typ = name
            #typ = cursor.get_definition().get_usr()
            log.debug("TYPEDEF_DECL: complex name:%s typ:%s id:%s"%(name,typ, _id))
        return self.register(name, typedesc.Typedef(name, typ))

    def _fixup_Typedef(self, t):
        #print 'fixing typdef %s name:%s with self.all[%s] = %s'%(id(t), t.name, t.typ, id(self.all[ t.typ])) 
        log.debug("_fixup_Typedef: t:'%s' t.typ:'%s' t.name:'%s'"%(t, t.typ, t.name))
        #print self.all.keys()
        if type(t.typ) == str: #typedesc.FundamentalType:
            t.typ = self.all[t.name]
        pass

    @log_entity
    def TYPE_REF(self, t):
        # Should probably never get here.
        #if not t.is_definition():
        #    log.debug('TYPE_REF: if not t.is_definition()')
        #    return
        # get the definition, create or reuse typedesc.
        next = t.type.get_declaration()
        _id = next.get_usr()
        log.debug('TYPE_REF: next:%s id:%s'%(next, _id))
        ##print '** _id is ', _id
        if _id in self.all:
            log.debug('TYPE_REF: _id in self.all')
            return self.all[_id]
        mth = getattr(self, next.kind.name)
        if mth is None:
            log.debug('TYPE_REF: mth is None')
            raise TypeError('unhandled Type_ref TypeKind %s'%(next.kind))
        log.debug('TYPE_REF: mth is %s'%(mth.__name__))
        res = mth(next)
        log.debug('TYPE_REF: res is %s'%(res.name))
        if res is not None:
            log.debug('TYPE_REF: self.all[%s] = %s'%(res.name, res))
            self.all[res.name] = res
            return self.all[res.name]
        log.error('None on TYPE_REF')
        return
        
        
    def FundamentalType(self, typ):
        #print cursor.displayname
        #t = cursor.type.get_canonical().kind
        ctypesname = self.convert_to_ctypes(typ.kind)
        if typ.kind == TypeKind.VOID:
            size = align = 1
        else:
            size = typ.get_size()
            align = typ.get_align()
        return typedesc.FundamentalType( ctypesname, size, align )

    def _fixup_FundamentalType(self, t): pass

    @log_entity
    def POINTER(self, cursor):
        # get pointer size
        size = cursor.type.get_size() # not size of pointee
        align = cursor.type.get_align() 
        # we shortcut to canonical defs
        typ = cursor.type.get_pointee().get_canonical()
        log.debug("POINTER: size:%d align:%d typ:%s"%(size, align, typ))
        if self.is_fundamental_type(typ):
            p_type = self.FundamentalType(typ)
        elif typ.kind == TypeKind.RECORD:
            children = [c for c in cursor.get_children()]
            assert len(children) == 1 # 'There is %d children - not expected in PointerType'%(len(children)))
            assert children[0].kind == CursorKind.TYPE_REF#, 'Wasnt expecting a %s in PointerType'%(children[0].kind))
            p_type = children[0].get_definition().get_usr()
            if p_type in self.all:
                p_type = self.all[p_type]
            else: # forward declaration 
                child = children[0].type.get_declaration()
                mth = getattr(self, child.kind.name)
                if mth is None:
                    log.debug('POINTER: mth is None')
                    raise TypeError('unhandled POINTER TypeKind %s'%(child.kind))
                log.debug('POINTER: mth is %s'%(mth.__name__))
                res = mth(child)
                p_type = res
        else:
            raise TypeError('Unknown scenario in PointerType - %s'%(typ))
        log.debug("POINTER: p_type:'%s'"%(p_type.name))
        # return the pointer        
        return typedesc.PointerType( p_type, size, align)


    def _fixup_PointerType(self, p):
        #print '*** Fixing up PointerType', p.typ
        #import code
        #code.interact(local=locals())
        ##if type(p.typ.typ) != typedesc.FundamentalType:
        ##    p.typ.typ = self.all[p.typ.typ]
        if type(p.typ) == str:
            p.typ = self.all[p.typ]

    ReferenceType = POINTER
    _fixup_ReferenceType = _fixup_PointerType
    OffsetType = POINTER
    _fixup_OffsetType = _fixup_PointerType

    @log_entity
    def CONSTANTARRAY(self, cursor):
        size = cursor.type.get_array_size()
        typ = cursor.type.get_array_element_type().get_canonical()
        if self.is_fundamental_type(typ):
            typ = self.FundamentalType(typ)
        else:
            mth = getattr(self, typ.kind.name)
            if mth is None:
                raise TypeError('unhandled Field TypeKind %s'%(t.name))
            typ  = mth(cursor)
            if typ is None:
                return None

        #import code
        #code.interact(local=locals())
        
        return typedesc.ArrayType(typ, size)

    def _fixup_ArrayType(self, a):
        # FIXME
        #if type(a.typ) != typedesc.FundamentalType:
        #    a.typ = self.all[a.typ]
        pass

    def CvQualifiedType(self, attrs):
        # id, type, [const|volatile]
        typ = attrs["type"]
        const = attrs.get("const", None)
        volatile = attrs.get("volatile", None)
        return typedesc.CvQualifiedType(typ, const, volatile)

    def _fixup_CvQualifiedType(self, c):
        c.typ = self.all[c.typ]

    # callables
    
    #def Function(self, attrs):
    @log_entity
    def FUNCTION_DECL(self, cursor):
        # name, returns, extern, attributes
        #name = attrs["name"]
        #returns = attrs["returns"]
        #attributes = attrs.get("attributes", "").split()
        #extern = attrs.get("extern")
        name = cursor.displayname
        returns = None
        attributes = None
        extern = None
        # FIXME:
        # cursor.get_arguments() or see def PARM_DECL()
        return typedesc.Function(name, returns, attributes, extern)

    def _fixup_Function(self, func):
        #FIXME
        #func.returns = self.all[func.returns]
        #func.fixup_argtypes(self.all)
        pass

    def FunctionType(self, attrs):
        # id, returns, attributes
        returns = attrs["returns"]
        attributes = attrs.get("attributes", "").split()
        return typedesc.FunctionType(returns, attributes)
    
    def _fixup_FunctionType(self, func):
        func.returns = self.all[func.returns]
        func.fixup_argtypes(self.all)

    @log_entity
    def OperatorFunction(self, attrs):
        # name, returns, extern, attributes
        name = attrs["name"]
        returns = attrs["returns"]
        return typedesc.OperatorFunction(name, returns)

    def _fixup_OperatorFunction(self, func):
        func.returns = self.all[func.returns]

    def _Ignored(self, attrs):
        log.debug("_Ignored: name:'%s' "%(cursor.spelling))
        name = attrs.get("name", None)
        if not name:
            name = attrs["mangled"]
        return typedesc.Ignored(name)

    def _fixup_Ignored(self, const): pass

    Converter = Constructor = Destructor = OperatorMethod = _Ignored

    def Method(self, attrs):
        # name, virtual, pure_virtual, returns
        name = attrs["name"]
        returns = attrs["returns"]
        return typedesc.Method(name, returns)

    def _fixup_Method(self, m):
        m.returns = self.all[m.returns]
        m.fixup_argtypes(self.all)

    # working, except for parent not being a Typedesc.
    def PARM_DECL(self, p):
        parent = cursor.semantic_parent
        #    if parent is not None:
        #        parent.add_argument(typedesc.Argument(p.type.get_canonical(), p.name))
        return

    # Just ignore it.
    @log_entity
    def INTEGER_LITERAL(self, cursor):
        # FIXME : unhandled constant values.
        #print 'INTEGER_LITERAL'
        #import code
        #code.interact(local=locals())
        #print ' im a integer i=', self.get_token(cursor)
        #import code
        #code.interact(local=locals())
        return

    # enumerations

    @log_entity
    def ENUM_DECL(self, cursor):
        ''' Get the enumeration type'''
        # id, name
        #print '** ENUMERATION', cursor.displayname
        name = cursor.displayname
        #if name == '':
        #    #raise ValueError('could try get_usr()')
        #    name = MAKE_NAME( cursor.get_usr() )
        align = cursor.type.get_align() 
        size = cursor.type.get_size() 
        #print align, size
        return typedesc.Enumeration(name, size, align)

    def _fixup_Enumeration(self, e): pass

    @log_entity
    def ENUM_CONSTANT_DECL(self, cursor):
        ''' Get the enumeration values'''
        name = cursor.displayname
        value = cursor.enum_value
        # FIXME obselete context by semantic_parent
        parent = self.all[cursor.semantic_parent.get_usr()]
        #parent = self.all[self.context[-1].get_usr()]        
        v = typedesc.EnumValue(name, value, parent)
        parent.add_value(v)
        return v

    def _fixup_EnumValue(self, e): pass

    # structures, unions, classes

    @log_entity
    def RECORD(self, cursor):
        ''' a record is a NOT a declaration ? '''
        # I'm a field. ?
        _type = cursor.type.get_declaration() 
        name = _type.spelling
        if name == '': 
            name = MAKE_NAME( cursor.get_usr() )
        kind = _type.kind
        if name in self.records:
            return self.records[name]
        #import code
        #code.interact(local=locals())
        log.debug("RECORD: TypeKind:'%s'"%(kind.name))
        mth = getattr(self, kind.name)
        if mth is None:
            raise TypeError('unhandled Record TypeKind %s'%(kind.name))
        self.records[name] = mth(cursor)
        return self.records[name]
        ## if next == CursorKind.TYPE_REF: # defer
        ## if next == CursorKind.UNION_DECL: # create
        ## if next == CursorKind.STRUCT_DECL: # create


    @log_entity
    def STRUCT_DECL(self, cursor):
        if not cursor.is_definition():
            return
        # id, name, members
        name = cursor.displayname
        if name == '': # anonymous is spelling == ''
            name = MAKE_NAME( cursor.get_usr() )
        if name in codegenerator.dont_assert_size:
            return typedesc.Ignored(name)
        # FIXME: lets ignore bases for now.
        #bases = attrs.get("bases", "").split() # that for cpp ?
        bases = [] # FIXME: support CXX

        align = cursor.type.get_align() 
        size = cursor.type.get_size()  

        members = []
        packed = False # 
        for child in cursor.get_children():
            if child.kind == clang.cindex.CursorKind.FIELD_DECL:
                members.append( child.get_usr())
                continue
            # FIXME LLVM-CLANG, patch http://lists.cs.uiuc.edu/pipermail/cfe-commits/Week-of-Mon-20130415/078445.html
            #if child.kind == clang.cindex.CursorKind.PACKED_ATTR:
            #    packed = True
        obj = typedesc.Structure(name, align, members, bases, size, packed=packed)
        #obj = typedesc.Structure(name, align, members, bases, size)
        self.records[name] = obj

        return obj

    def _make_padding(self, name, offset, length):
        log.debug("_make_padding: for %d bits"%(length))
        if (length % 8) != 0:
            # FIXME
            log.warning('_make_padding: FIXME we need sub-bytes padding definition')
        if length > 8:
            bytes = length/8
            return typedesc.Field(name,
                     typedesc.ArrayType(
                       typedesc.FundamentalType(
                         self.ctypes_typename[TypeKind.CHAR_U], length, 1 ),
                       bytes),
                     offset, length)
        return typedesc.Field(name,
                 typedesc.FundamentalType( self.ctypes_typename[TypeKind.CHAR_U], 1, 1 ),
                 offset, length)

    def _fixup_Structure(self, s):
        log.debug('RECORD_FIX: %s '%(s.name))
        import code
        #code.interact(local=locals())
        #print 'before', s.members
        #for m in s.members:
        #    if m not in self.all:
        #        print s.name,s.location
        members = []
        offset = 0
        padding_nb = 0
        # create padding fields
        for m in s.members:
            if m not in self.all or type(self.all[m]) != typedesc.Field:
                import code
                log.warning('Fixup_struct: Member unexpected : %s'%(m.name))
                #continue
                #code.interact(local=locals())
                raise TypeError('Fixup_struct: Member unexpected : %s'%(m))
            member = self.all[m]
            log.debug('Fixup_struct: Member:%s offset:%d-%d expecting offset:%d'%(
                    member.name, member.offset, member.offset + member.bits, offset))
            if member.offset > offset:
                #create padding
                length = member.offset - offset
                log.debug('Fixup_struct: create padding for %d bits %d bytes'%(length, length/8))
                p_name = 'PADDING_%d'%padding_nb
                padding = self._make_padding(p_name, offset, length)
                members.append(padding)
                padding_nb+=1
            if member.type is None:
                log.error('FIXUP_STRUCT: %s.type is None'%(member.name))
            members.append(member)
            offset = member.offset + member.bits
        # tail padding
        # FIXME: this isn't right. Why does Union.size returns 1.
        # Probably because of sizeof returning standard size instead of real size
        if s.size*8 != offset:
            length = s.size*8 - offset
            log.debug('Fixup_struct: s:%d create tail padding for %d bits %d bytes'%(s.size, length, length/8))
            p_name = 'PADDING_%d'%padding_nb
            padding = self._make_padding(p_name, offset, length)
            members.append(padding)
        offset = members[-1].offset + members[-1].bits
        # go
        s.members = members
        log.debug("FIXUP_STRUCT: size:%d offset:%d"%(s.size*8, offset))
        assert offset == s.size*8 #, assert that the last field stop at the size limit
        pass
    _fixup_Union = _fixup_Structure

    @log_entity
    def UNION_DECL(self, cursor):
        name = cursor.displayname
        if name == '': # anonymous is spelling == ''
            name = MAKE_NAME( cursor.get_usr() )
        bases = [] # FIXME: support CXX
        align = cursor.type.get_align()
        size = cursor.type.get_size() 
        members = [ child.get_usr() for child in cursor.get_children() if child.kind == clang.cindex.CursorKind.FIELD_DECL ]
        obj = typedesc.Union(name, align, members, bases, size)
        self.records[name] = obj
        return obj

    Class = STRUCT_DECL
    _fixup_Class = _fixup_Structure

    @log_entity
    def FIELD_DECL(self, cursor):
        # name, type
        name = cursor.displayname
        offset = cursor.semantic_parent.type.get_offset(name) 
        # bitfield
        bits = None
        if cursor.is_bitfield():
            bits = cursor.get_bitfield_width()
        else:
            bits = cursor.type.get_size() * 8
        # try to get a representation of the type
        t = cursor.type.get_canonical()
        typ = None
        if self.is_fundamental_type(t):
            typ = self.FundamentalType(t)
        else: # t.kind == TypeKind.RECORD or t.kind == TypeKind.POINTER and others
            # need to get the type
            log.debug("FIELD_DECL: TypeKind:'%s'"%(t.kind.name))
            mth = getattr(self, t.kind.name)
            if mth is None:
                raise TypeError('unhandled Field TypeKind %s'%(t.name))
            typ = mth(cursor)
            
            if typ is None:
                
                print '669'
                import code, sys
                #code.interact(local=locals())
                
                return None
                #raise TypeError('Field can not be None %s %s'%(name, t.nacursor.semantic_parent.typeme))   
        #else:
        #    log.debug("FIELD_DECL: TypeKind:'%s'"%(t.kind.name))
        #    import code, sys
        #    code.interact(local=locals())

        return typedesc.Field(name, typ, offset, bits, is_bitfield=cursor.is_bitfield())

    def _fixup_Field(self, f):
        #print 'fixup field', f.type
        #if f.type is not None:
        #    mth = getattr(self, '_fixup_%s'%(type(f.type).__name__))
        #    mth(f.type)
        pass

    ################

    def _fixup_Macro(self, m):
        pass

    def get_macros(self, text):
        if text is None:
            return
        text = "".join(text)
        # preprocessor definitions that look like macros with one or more arguments
        for m in text.splitlines():
            name, body = m.split(None, 1)
            name, args = name.split("(", 1)
            args = "(%s" % args
            self.all[name] = typedesc.Macro(name, args, body)

    def get_aliases(self, text, namespace):
        if text is None:
            return
        # preprocessor definitions that look like aliases:
        #  #define A B
        text = "".join(text)
        aliases = {}
        for a in text.splitlines():
            name, value = a.split(None, 1)
            a = typedesc.Alias(name, value)
            aliases[name] = a
            self.all[name] = a

        for name, a in aliases.items():
            value = a.alias
            # the value should be either in namespace...
            if value in namespace:
                # set the type
                a.typ = namespace[value]
            # or in aliases...
            elif value in aliases:
                a.typ = aliases[value]
            # or unknown.
            else:
                # not known
##                print "skip %s = %s" % (name, value)
                pass

    def get_result(self):
        interesting = (typedesc.Typedef, typedesc.Enumeration, typedesc.EnumValue,
                       typedesc.Function, typedesc.Structure, typedesc.Union,
                       typedesc.Variable, typedesc.Macro, typedesc.Alias )
                       #typedesc.Field) #???

        self.get_macros(self.cpp_data.get("functions"))
        
        remove = []
        for n, i in self.all.items():
            location = getattr(i, "location", None)
            # FIXME , why do we get different lcation types
            if location and hasattr(location, 'file'):
                i.location = location.file.name, location.line
            mth = getattr(self, "_fixup_" + type(i).__name__)
            try:
                mth(i)
            except IOError,e:#KeyError,e: # XXX better exception catching
                log.warning('function "%s" missing, err:%s, remove %s'%("_fixup_" + type(i).__name__, e, n) )
                remove.append(n)

        for n in remove:
            del self.all[n]

        # Now we can build the namespace.
        namespace = {}
        for i in self.all.values():
            if not isinstance(i, interesting):
                #log.debug('ignoring %s'%( i) )
                continue  # we don't want these
            name = getattr(i, "name", None)
            if name is not None:
                namespace[name] = i
        self.get_aliases(self.cpp_data.get("aliases"), namespace)

        result = []
        for i in self.all.values():
            if isinstance(i, interesting):
                result.append(i)

        #print 'self.all', self.all
        import code
        #code.interact(local=locals())
        
        #print 'clangparser get_result:',result
        return result
    
    #catch-all
    def __getattr__(self, name):
        if name not in self._unhandled:
            log.debug('%s is not handled'%(name))
            self._unhandled.append(name)
        def p(node):
            for child in node.get_children():
                self.startElement( child ) 
        return p

################################################################

def parse(args):
    # parse an XML file into a sequence of type descriptions
    parser = Clang_Parser()
    parser.parse(args)
    return parser.get_result()