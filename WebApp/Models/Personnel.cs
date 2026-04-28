using SmartSecuritySystem.Models;
using System;
using System.Collections.Generic;

namespace SmartSecuritySystem.ViewModels
{
    public class PersonnelManagementViewModel
    {
        // For Dashboard Login Users (Security/Admins)
        public List<User> SystemUsers { get; set; } = new List<User>();

        // For Campus Entry Members (Students/Staff)
        public List<AuthorizedMember> CampusMembers { get; set; } = new List<AuthorizedMember>();
    }

    public class AuthorizedMember 
    {
        public int Id { get; set; }
        public string FullName { get; set; } = string.Empty;
        public string Email { get; set; } = string.Empty;
        public string Phone { get; set; } = string.Empty; // Added
        public string Department { get; set; } = string.Empty;
        public string RfidTag { get; set; } = string.Empty;
        public string Status { get; set; } = "active"; // Added
        public string SecurityLevel { get; set; } = "normal"; // Added
        public bool HasFaceData { get; set; }
        public DateTime? CreatedAt { get; set; } // Added for "Joined Date"
        public DateTime? LastAccess { get; set; }
    }
}