import { z, type ZodTypeAny, type ZodObject } from 'zod';

export interface HelpJsonArg {
  name: string;
  type: 'str' | 'int' | 'float' | 'bool';
  required: boolean;
  /** True if argparse treats this as a positional argument (no `--flag` prefix).
   *  Crucial for the executor: positional values are appended in declaration
   *  order, optional flags are passed as `--name value`. The earlier code
   *  inferred "required" → "positional" which broke for argparse subcommands
   *  that have BOTH a positional + a required-but-flag arg (e.g. cover-set-tilt
   *  with positional entity_id + required --tilt-position). */
  positional?: boolean;
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
    case 'str': default:
      // Strings whose description hints they carry JSON (e.g. call-service
      // --data: '{"temperature": 21}') should accept either a real string OR
      // a literal object/array from the model — we serialize to JSON before
      // handing off to the subprocess. Without this Gemma's natural output of
      // `data: {position: 50}` hits a Zod type-mismatch and the whole tool
      // call fails with AI_ToolExecutionError.
      if (arg.description && /JSON/.test(arg.description)) {
        return z.union([z.string(), z.record(z.any()), z.array(z.any())])
          .transform((v) => (typeof v === 'string' ? v : JSON.stringify(v)));
      }
      return z.string();
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
