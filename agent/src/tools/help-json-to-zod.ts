import { z, type ZodTypeAny, type ZodObject } from 'zod';

export interface HelpJsonArg {
  name: string;
  type: 'str' | 'int' | 'float' | 'bool';
  required: boolean;
  description: string;
  choices?: Array<string | number>;
  default?: unknown;
  nargs?: '+' | '*';
}

export interface HelpJsonCommand {
  description: string;
  is_write: boolean;
  args: HelpJsonArg[];
}

export interface HelpJsonScript {
  description: string;
  commands: Record<string, HelpJsonCommand>;
}

function baseSchema(arg: HelpJsonArg): ZodTypeAny {
  if (arg.choices && arg.choices.length > 0) {
    if (typeof arg.choices[0] === 'number') {
      const literals = arg.choices.map(c => z.literal(c));
      return z.union(literals as unknown as [ZodTypeAny, ZodTypeAny, ...ZodTypeAny[]]);
    }
    return z.enum(arg.choices as [string, ...string[]]);
  }
  switch (arg.type) {
    case 'int': return z.number().int();
    case 'float': return z.number();
    case 'bool': return z.boolean();
    case 'str': default: return z.string();
  }
}

export function argToZod(arg: HelpJsonArg): ZodTypeAny {
  let schema: ZodTypeAny = baseSchema(arg);
  if (arg.nargs === '+' || arg.nargs === '*') {
    schema = arg.nargs === '+' ? z.array(schema).min(1) : z.array(schema);
  }
  if (arg.description) schema = schema.describe(arg.description);
  if (arg.default !== undefined) {
    schema = schema.default(arg.default as never);
  } else if (!arg.required) {
    schema = schema.optional();
  }
  return schema;
}

export function commandToZod(cmd: HelpJsonCommand): ZodObject<Record<string, ZodTypeAny>> {
  const shape: Record<string, ZodTypeAny> = {};
  for (const arg of cmd.args) {
    shape[arg.name] = argToZod(arg);
  }
  return z.object(shape);
}
