"""
RAG Data Loader for Agent Kernel
Loads documentation and example files from the cloned repository
"""
import os
from pathlib import Path
from typing import List, Optional
from llama_index.core import Document
from llama_index.readers.file import FlatReader


class AgentKernelDataLoader:
    """Load all relevant files from the Agent Kernel repository for RAG."""
    
    def __init__(self, repo_path: str = "/tmp/agent-kernel-rag"):
        """
        Initialize the data loader.
        
        :param repo_path: Path to the cloned agent-kernel repository
        """
        self.repo_path = Path(repo_path)
        if not self.repo_path.exists():
            raise ValueError(f"Repository path does not exist: {repo_path}")
        
        self.examples_path = self.repo_path / "examples"
        self.docs_path = self.repo_path / "docs" / "docs"
        
    def _should_include_file(self, file_path: Path) -> bool:
        """
        Determine if a file should be included in the RAG index.
        
        Includes: .py, .md, .toml, .yaml, .yml, .sh, .json, .txt files
        Excludes: __pycache__, .venv, node_modules, build artifacts, lock files
        """
        # File extensions to include
        valid_extensions = {'.py', '.md', '.toml', '.yaml', '.yml', '.sh', '.json', '.txt', '.rst'}
        
        # Directories and files to exclude
        exclude_patterns = {
            '__pycache__', '.venv', 'venv', 'node_modules', '.git', '.idea',
            'build', 'dist', '.pytest_cache', '.mypy_cache', 'htmlcov',
            '.gitignore', '.DS_Store'
        }
        
        # Exclude lock files
        if file_path.name in {'uv.lock', 'package-lock.json', 'poetry.lock', 'Pipfile.lock'}:
            return False
        
        # Check if any part of the path contains excluded patterns
        for part in file_path.parts:
            if part in exclude_patterns:
                return False
        
        # Check file extension
        return file_path.suffix in valid_extensions
    
    def load_markdown_docs(self) -> List[Document]:
        """Load all Markdown files from the docs / docs directory."""
        documents = []
        
        if not self.docs_path.exists():
            print(f"Warning: Documentation path not found: {self.docs_path}")
            return documents
        
        for md_file in self.docs_path.rglob("*.md"):
            try:
                with open(md_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                relative_path = md_file.relative_to(self.docs_path)
                doc = Document(
                    text=content,
                    metadata={
                        "file_path": str(relative_path),
                        "file_name": md_file.name,
                        "source_type": "documentation",
                        "full_path": str(md_file),
                    }
                )
                documents.append(doc)
            except Exception as e:
                print(f"Error reading {md_file}: {e}")
                continue
        
        print(f"Loaded {len(documents)} documentation files")
        return documents
    
    def load_example_files(self) -> List[Document]:
        """Load all relevant files from examples directory."""
        documents = []
        
        if not self.examples_path.exists():
            print(f"Warning: Examples path not found: {self.examples_path}")
            return documents
        
        for file_path in self.examples_path.rglob("*"):
            if not file_path.is_file():
                continue
            
            if not self._should_include_file(file_path):
                continue
            
            try:
                # Try to read as text
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                relative_path = file_path.relative_to(self.examples_path)
                
                # Extract example project name (first directory in path)
                project_name = relative_path.parts[0] if relative_path.parts else "unknown"
                
                doc = Document(
                    text=content,
                    metadata={
                        "file_path": str(relative_path),
                        "file_name": file_path.name,
                        "file_type": file_path.suffix,
                        "example_project": project_name,
                        "source_type": "example",
                        "full_path": str(file_path),
                    }
                )
                documents.append(doc)
            except UnicodeDecodeError:
                # Skip binary files
                continue
            except Exception as e:
                print(f"Error reading {file_path}: {e}")
                continue
        
        print(f"Loaded {len(documents)} example files")
        return documents
    
    def load_all_documents(self) -> List[Document]:
        """Load all documents from both docs and examples."""
        print("Loading Agent Kernel documentation and examples...")
        
        docs = self.load_markdown_docs()
        examples = self.load_example_files()
        
        all_documents = docs + examples
        print(f"Total documents loaded: {len(all_documents)}")
        
        return all_documents
