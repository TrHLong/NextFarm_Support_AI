from __future__ import annotations
import gzip, math, struct
from pathlib import Path
from typing import Mapping, Sequence, Any

# Minimal standard-library Parquet writer for FLAT REQUIRED columns.
# Encoding: PLAIN. Compression: GZIP or UNCOMPRESSED.
# Types: UTF-8 BYTE_ARRAY, INT64, DOUBLE.
# Purpose: bootstrap/package data before pyarrow is installed on the host.

PARQUET_INT64=2; PARQUET_DOUBLE=5; PARQUET_BYTE_ARRAY=6
REQUIRED=0
PLAIN=0; RLE=3
UNCOMPRESSED=0; GZIP=2
DATA_PAGE=0
UTF8=0  # ConvertedType.UTF8

# Thrift Compact Protocol type ids.
CT_STOP=0; CT_TRUE=1; CT_FALSE=2; CT_BYTE=3; CT_I16=4; CT_I32=5; CT_I64=6; CT_DOUBLE=7; CT_BINARY=8; CT_LIST=9; CT_SET=10; CT_MAP=11; CT_STRUCT=12

class CompactWriter:
    def __init__(self):
        self.buf=bytearray(); self._last=0; self._stack=[]
    def struct_begin(self): self._stack.append(self._last); self._last=0
    def struct_end(self): self._last=self._stack.pop()
    def stop(self): self.buf.append(CT_STOP)
    def _uvar(self,n:int):
        n=int(n)
        while True:
            b=n & 0x7f; n >>= 7
            if n: self.buf.append(b|0x80)
            else: self.buf.append(b); return
    @staticmethod
    def _zig(n:int)->int: return (int(n)<<1) ^ (int(n)>>63)
    def field(self,ctype:int,fid:int):
        delta=fid-self._last
        if 0 < delta <= 15: self.buf.append((delta<<4)|ctype)
        else:
            self.buf.append(ctype); self._uvar(self._zig(fid))
        self._last=fid
    def i32(self,n:int): self._uvar(self._zig(n))
    def i64(self,n:int): self._uvar(self._zig(n))
    def binary(self,s:str|bytes):
        b=s if isinstance(s,bytes) else str(s).encode('utf-8')
        self._uvar(len(b)); self.buf.extend(b)
    def list_begin(self,elem_ctype:int,size:int):
        if size < 15: self.buf.append((size<<4)|elem_ctype)
        else: self.buf.append(0xF0|elem_ctype); self._uvar(size)


def _compact_bytes(write_fn)->bytes:
    p=CompactWriter(); write_fn(p); return bytes(p.buf)


def _write_data_page_header(num_values:int, uncompressed_size:int, compressed_size:int)->bytes:
    def w(p:CompactWriter):
        p.struct_begin()
        p.field(CT_I32,1); p.i32(DATA_PAGE)
        p.field(CT_I32,2); p.i32(uncompressed_size)
        p.field(CT_I32,3); p.i32(compressed_size)
        p.field(CT_STRUCT,5)
        p.struct_begin()
        p.field(CT_I32,1); p.i32(num_values)
        p.field(CT_I32,2); p.i32(PLAIN)
        p.field(CT_I32,3); p.i32(RLE)
        p.field(CT_I32,4); p.i32(RLE)
        p.stop(); p.struct_end()
        p.stop(); p.struct_end()
    return _compact_bytes(w)


def _write_schema_element(p:CompactWriter,name:str,kind:str|None=None,root_children:int|None=None):
    p.struct_begin()
    if kind is not None:
        typ={'string':PARQUET_BYTE_ARRAY,'int64':PARQUET_INT64,'double':PARQUET_DOUBLE}[kind]
        p.field(CT_I32,1); p.i32(typ)
        p.field(CT_I32,3); p.i32(REQUIRED)
    p.field(CT_BINARY,4); p.binary(name)
    if root_children is not None:
        p.field(CT_I32,5); p.i32(root_children)
    if kind=='string':
        p.field(CT_I32,6); p.i32(UTF8)
    p.stop(); p.struct_end()


def _write_column_metadata(p:CompactWriter,c):
    p.struct_begin()
    typ={'string':PARQUET_BYTE_ARRAY,'int64':PARQUET_INT64,'double':PARQUET_DOUBLE}[c['kind']]
    p.field(CT_I32,1); p.i32(typ)
    p.field(CT_LIST,2); p.list_begin(CT_I32,2); p.i32(PLAIN); p.i32(RLE)
    p.field(CT_LIST,3); p.list_begin(CT_BINARY,1); p.binary(c['name'])
    p.field(CT_I32,4); p.i32(c['codec'])
    p.field(CT_I64,5); p.i64(c['num_values'])
    p.field(CT_I64,6); p.i64(c['uncompressed_size'])
    p.field(CT_I64,7); p.i64(c['compressed_size'])
    p.field(CT_I64,9); p.i64(c['offset'])
    p.stop(); p.struct_end()


def _write_column_chunk(p:CompactWriter,c):
    p.struct_begin()
    p.field(CT_I64,2); p.i64(c['offset'])
    p.field(CT_STRUCT,3); _write_column_metadata(p,c)
    p.stop(); p.struct_end()


def _footer_bytes(schema,num_rows,chunks)->bytes:
    def w(p:CompactWriter):
        p.struct_begin()
        p.field(CT_I32,1); p.i32(1)
        p.field(CT_LIST,2); p.list_begin(CT_STRUCT,len(schema)+1)
        _write_schema_element(p,'schema',root_children=len(schema))
        for name,kind in schema: _write_schema_element(p,name,kind)
        p.field(CT_I64,3); p.i64(num_rows)
        p.field(CT_LIST,4); p.list_begin(CT_STRUCT,1)
        p.struct_begin()
        p.field(CT_LIST,1); p.list_begin(CT_STRUCT,len(chunks))
        for c in chunks: _write_column_chunk(p,c)
        total=sum(c['uncompressed_size'] for c in chunks)
        compressed_total=sum(c['compressed_size'] for c in chunks)
        p.field(CT_I64,2); p.i64(total)
        p.field(CT_I64,3); p.i64(num_rows)
        p.field(CT_I64,6); p.i64(compressed_total)
        p.stop(); p.struct_end()
        p.field(CT_BINARY,6); p.binary('NextFarm minimal parquet writer')
        p.stop(); p.struct_end()
    return _compact_bytes(w)


def _infer_kind(values: Sequence[Any])->str:
    saw=False; all_int=True; all_num=True
    for v in values:
        if v is None or v=='': continue
        saw=True
        try:
            f=float(v)
            if not math.isfinite(f): all_int=False
            if isinstance(v,str) and any(x in v.lower() for x in ('.','e')): all_int=False
            elif f != int(f): all_int=False
        except Exception:
            all_num=False; all_int=False; break
    if saw and all_int: return 'int64'
    if saw and all_num: return 'double'
    return 'string'


def _plain_body(values: Sequence[Any],kind:str)->bytes:
    out=bytearray()
    if kind=='string':
        for v in values:
            s='' if v is None else str(v); b=s.encode('utf-8')
            out += struct.pack('<i',len(b)); out += b
    elif kind=='int64':
        for v in values:
            try: x=int(float(v))
            except Exception: x=0
            out += struct.pack('<q',x)
    elif kind=='double':
        for v in values:
            try: x=float(v)
            except Exception: x=float('nan')
            out += struct.pack('<d',x)
    else: raise ValueError(kind)
    return bytes(out)


def write_columns(path: str|Path,columns: Mapping[str,Sequence[Any]],schema: Mapping[str,str]|None=None,compression: str='gzip')->None:
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    names=list(columns)
    if not names: raise ValueError('No columns')
    n=len(columns[names[0]])
    if any(len(columns[k])!=n for k in names): raise ValueError('Column lengths differ')
    schema_list=[(name,(schema or {}).get(name) or _infer_kind(columns[name])) for name in names]
    chunks=[]
    with path.open('wb') as f:
        f.write(b'PAR1')
        for name,kind in schema_list:
            body=_plain_body(columns[name],kind)
            if compression=='gzip': payload=gzip.compress(body,compresslevel=6,mtime=0); codec=GZIP
            elif compression in {'none','uncompressed',None}: payload=body; codec=UNCOMPRESSED
            else: raise ValueError(f'Unsupported compression: {compression}')
            header=_write_data_page_header(n,len(body),len(payload))
            offset=f.tell(); f.write(header); f.write(payload)
            chunks.append({'name':name,'kind':kind,'num_values':n,'offset':offset,'codec':codec,'uncompressed_size':len(header)+len(body),'compressed_size':len(header)+len(payload)})
        footer=_footer_bytes(schema_list,n,chunks)
        f.write(footer); f.write(struct.pack('<I',len(footer))); f.write(b'PAR1')


def write_records(path: str|Path,records: Sequence[Mapping[str,Any]],fields: Sequence[str],schema: Mapping[str,str]|None=None,compression: str='gzip')->None:
    cols={k:[r.get(k) for r in records] for k in fields}
    write_columns(path,cols,schema=schema,compression=compression)
