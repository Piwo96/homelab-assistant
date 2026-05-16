import { describe, it, expect } from 'bun:test';
import { z } from 'zod';
import { commandToZod, type HelpJsonCommand } from '../src/tools/help-json-to-zod';

describe('commandToZod', () => {
  it('builds schema for required positional + optional flag', () => {
    const cmd: HelpJsonCommand = {
      description: 'Turn on entity',
      is_write: true,
      args: [
        { name: 'entity_id', type: 'str', required: true, description: 'Entity ID' },
        { name: 'brightness', type: 'int', required: false, description: 'Brightness 0-255' },
      ],
    };
    const schema = commandToZod(cmd);
    expect(schema.parse({ entity_id: 'light.kitchen' })).toEqual({ entity_id: 'light.kitchen' });
    expect(schema.parse({ entity_id: 'light.kitchen', brightness: 180 }))
      .toEqual({ entity_id: 'light.kitchen', brightness: 180 });
    expect(() => schema.parse({})).toThrow();
    expect(() => schema.parse({ entity_id: 'x', brightness: 'not-a-number' })).toThrow();
  });

  it('handles enum (choices)', () => {
    const cmd: HelpJsonCommand = {
      description: 'Set mode',
      is_write: true,
      args: [{ name: 'mode', type: 'str', required: true, description: '', choices: ['on', 'off', 'auto'] }],
    };
    const schema = commandToZod(cmd);
    expect(() => schema.parse({ mode: 'on' })).not.toThrow();
    expect(() => schema.parse({ mode: 'invalid' })).toThrow();
  });

  it('applies default when arg not provided', () => {
    const cmd: HelpJsonCommand = {
      description: 'List with limit',
      is_write: false,
      args: [{ name: 'limit', type: 'int', required: false, description: '', default: 10 }],
    };
    const schema = commandToZod(cmd);
    expect(schema.parse({}).limit).toBe(10);
  });

  it('handles boolean flags', () => {
    const cmd: HelpJsonCommand = {
      description: 'Verbose',
      is_write: false,
      args: [{ name: 'verbose', type: 'bool', required: false, description: '' }],
    };
    const schema = commandToZod(cmd);
    expect(schema.parse({ verbose: true }).verbose).toBe(true);
    expect(schema.parse({}).verbose).toBeUndefined();
  });

  it('handles nargs="+" as array', () => {
    const cmd: HelpJsonCommand = {
      description: 'Multi',
      is_write: false,
      args: [{ name: 'ids', type: 'str', required: true, description: '', nargs: '+' }],
    };
    const schema = commandToZod(cmd);
    expect(schema.parse({ ids: ['a', 'b'] }).ids).toEqual(['a', 'b']);
    expect(() => schema.parse({ ids: 'a' })).toThrow();
  });
});
