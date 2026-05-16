import type { ModelInfo } from '../types';

const QWEN_MODEL_PREFERENCE = [
  'qwen3.5:4b',
  'qwen3.5:2b',
  'qwen3.5:9b',
  'qwen3.5:0.8b',
  'qwen3.5:27b',
  'qwen3.5:35b',
  'qwen3.5:122b',
];

function normalizeModelId(modelId: string): string {
  return modelId.trim().toLowerCase();
}

export function isInstalledModel(modelId: string, models: ModelInfo[]): boolean {
  if (!modelId) return false;
  const needle = normalizeModelId(modelId);
  return models.some((model) => normalizeModelId(model.id) === needle);
}

export function findPreferredQwenModel(models: ModelInfo[]): string {
  const installed = new Map(
    models.map((model) => [normalizeModelId(model.id), model.id]),
  );

  for (const preferred of QWEN_MODEL_PREFERENCE) {
    const match = installed.get(normalizeModelId(preferred));
    if (match) return match;
  }

  return (
    models.find((model) => normalizeModelId(model.id).includes('qwen'))?.id || ''
  );
}

interface ResolveModelSelectionArgs {
  selectedModel?: string;
  defaultModel?: string;
  serverModel?: string;
  models: ModelInfo[];
}

export function resolveModelSelection({
  selectedModel = '',
  defaultModel = '',
  serverModel = '',
  models,
}: ResolveModelSelectionArgs): string {
  // Honor an explicit selection/default verbatim. A model that isn't
  // installed yet is pulled on demand by the Ollama engine
  // (OllamaEngine._ensure_model) rather than silently swapped here.
  const explicitSelected = selectedModel.trim();
  if (explicitSelected) return explicitSelected;

  const explicitDefault = defaultModel.trim();
  if (explicitDefault) return explicitDefault;

  const preferredQwen = findPreferredQwenModel(models);
  if (preferredQwen) return preferredQwen;

  const explicitServer = serverModel.trim();
  if (explicitServer) return explicitServer;
  return models[0]?.id || '';
}
