import syntax
from common import dispatch
from transform import Transform
import syntax_helpers 
from syntax_visitor import SyntaxVisitor 

class FindLiveVars(SyntaxVisitor):
  def __init__(self):
    self.live_vars = set([])
    
  def visit_Var(self, expr):
    self.live_vars.add(expr.name)
    
  def visit_lhs(self, expr):
    if isinstance(expr, syntax.Var):
      pass 
    elif isinstance(expr, syntax.Tuple):
      for elt in expr.elts:
        self.visit_lhs(elt)
    else:
      self.visit_expr(expr)
      
  def visit_fn(self, fn):
    self.live_vars.clear()
    for name in fn.arg_names:
      self.live_vars.add(name)
    self.visit_block(fn.body)
    return self.live_vars




class VarUseCount(SyntaxVisitor):
  
  def __init__(self):
    self.counts = {}
    
  def visit_Var(self, expr):
    old_count = self.counts.get(expr.name, 0)
    self.counts[expr.name] = old_count + 1 
    
  def visit_lhs(self, expr):
    if isinstance(expr, syntax.Var):
      pass 
    elif isinstance(expr, syntax.Tuple):
      for elt in expr.elts:
        self.visit_lhs(elt)
    else:
      self.visit_expr(expr)
      
  def visit_fn(self, fn):
    self.counts.clear()
    for name in fn.arg_names:
      self.counts[name] = 1
    self.visit_block(fn.body)
    return self.counts 
  


class DCE(Transform):
  def __init__(self, fn):
    Transform.__init__(self, fn, reverse = True)
    # self.live_vars = FindLiveVars().visit_fn(fn)
    self.use_counts = VarUseCount().visit_fn(fn)

    
  def is_live(self, name):
    return name in self.use_counts and self.use_counts[name] > 0
         
  def is_live_lhs(self, lhs):
    if isinstance(lhs, syntax.Var):
      return self.is_live(lhs.name)
    elif isinstance(lhs, syntax.Tuple):
      return any(self.is_live_lhs(elt) for elt in lhs.elts)
    elif isinstance(lhs, (str, tuple)):
      assert False, "Raw data? This ain't the stone age, you know."
    else:
      return True

  def transform_phi_nodes(self, phi_nodes):
    new_merge = {}
    for (var_name, (l,r)) in phi_nodes.iteritems():
      if self.is_live(var_name):
        new_merge[var_name] = phi_nodes[var_name]
      else:
        self.transform_expr(l)
        self.transform_expr(r)
    return new_merge
  
  def transform_Var(self, expr):
    """
    We should only reach this method if it's part of an 
    explicit call to transform_expr from the removal of 
    a statement or phi-node
    """
    self.use_counts[expr.name] -= 1 
    return expr 
  
  def transform_Assign(self, stmt):
    if self.is_live_lhs(stmt.lhs):
      return stmt
    else:
      self.transform_expr(stmt.rhs)
      return None

  
  
  def transform_While(self, stmt):
    # expressions don't get changed by this transform
    cond = stmt.cond
    new_body = self.transform_block(stmt.body) 
    new_merge = self.transform_phi_nodes(stmt.merge)
    if len(new_merge) == 0 and len(new_body) == 0:
      return None
    else:
      return syntax.While(cond, new_body, new_merge)

  def transform_If(self, stmt):
    cond = stmt.cond 
    new_true = self.transform_block(stmt.true) 
    new_false = self.transform_block(stmt.false)
    new_merge = self.transform_phi_nodes(stmt.merge)
    if len(new_merge) == 0 and len(new_true) == 0 and len(new_false) == 0:
      return None  
    elif syntax_helpers.is_true(cond):
      for name, (_, v) in new_merge.items():
        self.assign(syntax.Var(name, type = v.type), v)
      self.blocks.extend_current(reversed(stmt.true))
      return None 
    elif syntax_helpers.is_false(cond):
      for name, (v, _) in new_merge.items():
        self.assign(syntax.Var(name, type = v.type), v)
      self.blocks.extend_current(reversed(stmt.false))

      return None 
    else:
      return syntax.If(cond, new_true, new_false, new_merge)

  def transform_Return(self, stmt):

    return stmt
  
  def post_apply(self, fn):
    type_env = {} 
    for (name,t) in fn.type_env.iteritems():
      if self.is_live(name):
        type_env[name] = t
    fn.type_env = type_env 
    Transform.post_apply(self, fn)
    return fn 
  
def dead_code_elim(fn):
  dce = DCE(fn)
  return dce.apply(copy = False)
  