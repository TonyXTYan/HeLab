# TreePanelWidget Enhancement Plan

## Overview
Implement a flexible script loading and group switching system for TreePanelWidget that allows users to select and load Python analysis files from any directory.

## Components

### 1. Script Protocol Definition
- Create `HelabAnalysisScript` base class defining the required interface
- Required methods:
  - `get_metadata()` - returns script name, description, group
  - `get_actions()` - returns list of available actions 
  - `execute_action(action_name)` - runs a specific action
- Scripts should implement this interface to be recognized by the system

### 2. Script Discovery and Loading 
- Create `ScriptsManager` class to:
  - Allow users to select script directories
  - Scan directories for Python files
  - Validate files against protocol
  - Load and categorize scripts into groups
  - Cache loaded scripts for performance
- Handle script loading errors gracefully

### 3. TreePanelWidget Enhancements
1. Add directory selection:
   - Add button/menu item to select script directories
   - Save recently used directories
   - Monitor directory for changes

2. Add group selection:
   - Add combo box/dropdown for group selection
   - Implement group switching logic
   - Preserve state when switching groups
   - Handle empty groups

3. Script Loading Integration:
   - Parse script metadata for grouping
   - Create tree items from loaded scripts
   - Show script descriptions
   - Handle loading errors

### 4. Implementation Phases

#### Phase 1 - Core Structure
- Create base protocol class `HelabAnalysisScript`
- Implement `ScriptsManager` with basic loading
- Add directory selection UI
- Add group switching UI elements

#### Phase 2 - Integration
- Connect script loading to UI
- Implement action handling
- Add error handling
- Set up directory monitoring

#### Phase 3 - Polish
- Add loading animations
- Improve error messages
- Add script validation
- Implement script caching
- Save user preferences

## User Flow
1. User clicks "Select Script Directory" 
2. File dialog opens to select directory
3. System scans directory for Python files
4. Valid scripts are loaded and grouped
5. Groups appear in group selector
6. User can switch between groups
7. Scripts in selected group are displayed
8. User can execute script actions

## Error Handling
- Invalid script files
- Missing required methods
- Script loading failures
- Empty directories
- Runtime errors

## Future Enhancements
- Hot reloading of scripts
- Script dependencies management
- Custom group organization
- Script search/filtering
- Favorites system